-- Sliding window rate limiter

-- KEYS[1] = rate limit key
-- ARGV[1] = current timestamp
-- ARGV[2] = window size (seconds)
-- ARGV[3] = max requests

local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])

local window_start = now - window

-- remove expired entries
redis.call("ZREMRANGEBYSCORE", key, 0, window_start)

-- count remaining requests
local request_count = redis.call("ZCARD", key)

if request_count >= limit then
    return request_count
end

-- add current request
redis.call("ZADD", key, now, now)

-- ensure key expires eventually
redis.call("EXPIRE", key, window)

return request_count + 1