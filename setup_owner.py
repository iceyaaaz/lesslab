"""在自己的终端交互创建初始账号并接收旧数据；不要在命令参数中填写密码。"""
from getpass import getpass

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from security import initialize_owner


def main():
    from database import engine
    print("请先备份数据库、停止网页服务，并执行 005 数据库迁移。")
    username = input("初始用户名（3—32 位英文字母、数字或下划线）：")
    password = getpass("登录密码（15—128 个字符，输入时不显示）：")
    confirmation = getpass("再次输入密码：")
    if password != confirmation:
        print("两次密码不同，没有修改数据库。")
        return 1
    try:
        user_id = initialize_owner(engine, username, password)
    except (ValueError, HTTPException) as error:
        print(error.detail if isinstance(error, HTTPException) else str(error))
        return 1
    except SQLAlchemyError:
        print("初始化未完成，事务已回滚。请检查迁移、账号是否重名和数据库读写权限。")
        return 1
    print(f"初始账号创建成功（编号 {user_id}），原有收藏、计划和目标已归属此账号。")
    print("可以启动服务，用刚设置的用户名和密码登录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
