## Introduction

- This folder contains two scripts for a quick start-up
- The first script `db_user_setup.py` for creating postgresql database user and database.
- The Second script `gen_test_table_data.py` is for creating `products` table and populating with some `dummy` data.
- For the second script, tweak the `DATABASE_URL` accordingly. The default behaviour is an assumption that the host is running on port `5344` - informed by docker-compose configuration for `postgres` service.