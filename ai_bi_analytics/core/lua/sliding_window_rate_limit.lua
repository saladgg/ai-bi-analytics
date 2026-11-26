-- Sliding-window rate limiter (atomic check-and-record).
--
-- KEYS[1] = rate limit key (one sorted set per client)
-- ARGV[1] = window length in milliseconds
-- ARGV[2] = max requests per window
-- ARGV[3] = unique request id (member suffix)
--
-- Returns {allowed, count, retry_after_ms}
--   allowed        1 = request recorded and allowed, 0 = rejected
--   count          requests in the window, including this one if allowed
--   retry_after_ms when rejected, ms until the oldest entry leaves the window
--
-- Time comes from the Redis server (TIME), not from callers, so replicas
-- with skewed clocks share one timeline. Scores are milliseconds and each
-- member is unique, so concurrent requests in the same millisecond are all
-- counted (whole-second timestamp members used to collide and undercount).

local key = KEYS[1]
local window_ms = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local request_id = ARGV[3]

local t = redis.call("TIME")
local now_ms = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)

redis.call("ZREMRANGEBYSCORE", key, "-inf", now_ms - window_ms)

local count = redis.call("ZCARD", key)

if count >= limit then
    local oldest = redis.call("ZRANGE", key, 0, 0, "WITHSCORES")
    local retry_after_ms = window_ms
    if oldest[2] then
        retry_after_ms = math.max(tonumber(oldest[2]) + window_ms - now_ms, 1)
    end
    return {0, count, retry_after_ms}
end

redis.call("ZADD", key, now_ms, now_ms .. ":" .. request_id)
redis.call("PEXPIRE", key, window_ms)

return {1, count + 1, 0}
