import os
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from dotenv import load_dotenv
import logging

# 配置日志
logger = logging.getLogger("DB_Utils")

# 加载环境变量
load_dotenv()
DATABASE_URL = os.getenv("POSTGRES_URL")

# 初始化全局连接池
_db_pool = None

def init_db_pool():
    global _db_pool
    if _db_pool is None:
        try:
            _db_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=DATABASE_URL
            )
            logger.info("PostgreSQL 连接池初始化成功")
        except Exception as e:
            logger.error(f"连接池初始化失败: {e}")
            raise e

@contextmanager
def get_db_cursor():
    """
    上下文管理器：从连接池获取连接，创建字典游标，
    自动提交事务，最后归还连接。
    """
    global _db_pool
    # 确保连接池已初始化
    if _db_pool is None:
        init_db_pool()

    conn = None
    try:
        conn = _db_pool.getconn()
        # 使用 RealDictCursor 使得查询结果为字典格式
        cur = conn.cursor(cursor_factory=RealDictCursor)
        yield cur
        conn.commit()
        cur.close()
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            _db_pool.putconn(conn)


# --- 用于直接调试的 Main 方法 ---
if __name__ == "__main__":
    print("--- 开始测试数据库连接 ---")
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT version();")
            res = cur.fetchone()
            print(f"数据库连接成功! 版本信息: {res['version']}")
            
            cur.execute("SELECT count(*) as count FROM room_details;")
            res_room = cur.fetchone()
            print(f"room_details 表记录数: {res_room['count']}")
    except Exception as e:
        print(f"测试失败: {e}")