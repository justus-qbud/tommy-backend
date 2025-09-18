import inspect
import logging
import msgpack
import os
from functools import wraps

import redis


def create_redis_client():
    try:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        client = redis.Redis.from_url(redis_url)
        client.ping()
        logging.info("Redis available.")
        return client
    except Exception:
        logging.warning("Redis not available.")
        return None


REDIS = create_redis_client()


class RedisCache:
    @staticmethod
    def get(key, new_expiry=None):
        try:
            if REDIS is None:
                return None
            if new_expiry is not None:
                REDIS.expire(key, new_expiry)
            value = REDIS.get(key)
            if value is None:
                return None

            for data_type in (int, float):
                try:
                    return data_type(value)
                except ValueError:
                    continue

            try:
                return value.decode('utf-8')
            except (ValueError, AttributeError):
                return msgpack.unpackb(value, raw=False, strict_map_key=False)
        except Exception:
            return None

    @staticmethod
    def set(key, value, ex: int | None = None):
        try:
            if REDIS is None:
                return False
            if isinstance(value, bool):
                REDIS.set(key, int(value), ex=ex)
            elif isinstance(value, (str, int, float)):
                REDIS.set(key, value, ex=ex)
            else:
                packed_value = msgpack.packb(value, use_bin_type=True)
                REDIS.set(key, packed_value, ex=ex)
            return True
        except Exception:
            return False

    @staticmethod
    def delete(key):
        try:
            if REDIS is None:
                return False
            return REDIS.delete(key)
        except Exception:
            return False

    @staticmethod
    def add_to_set(key, value, ex: int | None = None):
        try:
            if REDIS is None:
                return False
            pipeline = REDIS.pipeline()
            pipeline.sadd(key, value)
            if ex is not None:  # Fixed: was checking if ex is None
                pipeline.expire(key, ex)
            pipeline.execute()
            return True
        except Exception:
            return False

    @staticmethod
    def remove_from_set(key, value):
        try:
            if REDIS is None:
                return False
            return REDIS.srem(key, value)
        except Exception:
            return False

    @staticmethod
    def is_in_set(key, value):
        try:
            if REDIS is None:
                return False
            return REDIS.sismember(key, value)
        except Exception:
            return False

    @staticmethod
    def get_set(key):
        try:
            if REDIS is None:
                return set()
            return REDIS.smembers(key)
        except Exception:
            return set()

    @staticmethod
    def incr(key):
        try:
            if REDIS is None:
                return None
            return REDIS.incr(key)
        except Exception:
            return None

    @staticmethod
    def decrby(key, amount):
        try:
            if REDIS is None:
                return None
            return REDIS.decrby(key, amount)
        except Exception:
            return None

    @staticmethod
    def incrby(key, amount):
        try:
            if REDIS is None:
                return None
            return REDIS.incrby(key, amount)
        except Exception:
            return None

    @staticmethod
    def expire(key, ex):
        try:
            if REDIS is None:
                return False
            return REDIS.expire(key, ex)
        except Exception:
            return False

    @staticmethod
    def print_cache_keys(resource):
        try:
            if REDIS is None:
                print("Redis unavailable")
                return
            pattern = "*/" + resource + "*"
            for key in REDIS.scan_iter(pattern):
                print(key)
        except Exception:
            print("Error scanning cache keys")

    @staticmethod
    def scan_iter(search_key):
        try:
            if REDIS is None:
                return iter([])  # Return empty iterator
            return REDIS.scan_iter(search_key)
        except Exception:
            return iter([])

    @staticmethod
    def delete_fuzzy(substring, starts_with: bool = False, ends_with: bool = False):
        try:
            if REDIS is None:
                return False
            cursor = '0'
            pipeline = REDIS.pipeline()
            while cursor != 0:
                cursor, keys = REDIS.scan(
                    cursor=cursor,
                    match=f"{'' if starts_with else '*'}{substring}{'' if ends_with else '*'}",
                    count=1000
                )
                if keys:
                    pipeline.delete(*keys)
            pipeline.execute()
            return True
        except Exception:
            return False

    @staticmethod
    def delete_pattern(pattern):
        try:
            if REDIS is None:
                return False
            cursor = '0'
            pipeline = REDIS.pipeline()
            while cursor != 0:
                cursor, keys = REDIS.scan(cursor=cursor, match=pattern, count=1000)
                if keys:
                    pipeline.delete(*keys)
            pipeline.execute()
            return True
        except Exception:
            return False

    @staticmethod
    def add_to_hset(hset_key, key, value, max_length: int = 1000):
        try:
            if REDIS is None:
                return False
            pipeline = REDIS.pipeline()
            pipeline.hset(hset_key, key, value)
            pipeline.lpush(f"{hset_key}_order", key)
            pipeline.ltrim(f"{hset_key}_order", 0, max_length - 1)

            # Check if we need to remove old entries
            if REDIS.llen(f"{hset_key}_order") >= max_length:
                oldest_id = REDIS.rpop(f"{hset_key}_order")
                if oldest_id:
                    pipeline.hdel(hset_key, oldest_id)

            pipeline.execute()
            return True
        except Exception:
            return False

def redis_cache(key_pattern, ex=300):
    """Decorator for caching function results in Redis."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()

            all_args = bound_args.arguments

            if args and list(all_args.keys())[0] in ['self', 'cls']:
                all_args = dict(all_args)
                first_key = list(all_args.keys())[0]
                del all_args[first_key]

            try:
                redis_key = key_pattern.format(**all_args)
            except KeyError as e:
                raise ValueError(f"Key pattern references argument '{e}' not present in function call")

            # Check if data is in Redis cache
            if cached_data := RedisCache.get(redis_key):
                return cached_data

            result = func(*args, **kwargs)

            RedisCache.set(redis_key, result, ex=ex if result else 30)

            return result

        return wrapper

    return decorator


def redis_cache_bust(key_patterns: list | str):
    """Decorator for invalidating Redis cache entries."""

    if isinstance(key_patterns, str):
        key_patterns = [key_patterns]

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # First call the original function
            result = func(*args, **kwargs)

            # Get the argument names from the function
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()

            # Create a dictionary with all arguments (positional and keyword)
            all_args = bound_args.arguments

            # If it's a method, remove 'self' or 'cls' from arguments
            if args and list(all_args.keys())[0] in ['self', 'cls']:
                all_args = dict(all_args)
                first_key = list(all_args.keys())[0]
                del all_args[first_key]

            # Process each key pattern
            for key_pattern in key_patterns:
                # Check if we need to do wildcard deletion
                if '*' in key_pattern:
                    # Handle wildcard in the pattern
                    parts = key_pattern.split('*', 1)  # Split on first '*'
                    pattern_prefix = parts[0]
                    pattern_suffix = parts[1] if len(parts) > 1 else ""

                    # Format the parts with available arguments if needed
                    try:
                        formatted_prefix = pattern_prefix.format(**all_args)
                    except KeyError:
                        formatted_prefix = pattern_prefix

                    try:
                        formatted_suffix = pattern_suffix.format(**all_args)
                    except KeyError:
                        formatted_suffix = pattern_suffix

                    # Construct the final pattern: formatted_prefix + * + formatted_suffix
                    final_pattern = f"{formatted_prefix}*{formatted_suffix}"
                    RedisCache.delete_pattern(final_pattern)
                else:
                    # Format the Redis key using the provided pattern and arguments
                    try:
                        redis_key = key_pattern.format(**all_args)
                    except KeyError as e:
                        raise ValueError(f"Key pattern references argument '{e}' not present in function call")

                    # Delete the specific key
                    RedisCache.delete(redis_key)

            return result

        return wrapper

    return decorator
