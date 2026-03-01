"""
数据库初始化和测试脚本

此脚本用于：
1. 删除所有旧表（如果存在）
2. 创建新的表结构
3. 插入测试数据
4. 验证新模型的基本CRUD操作
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import database
from app.database import init_database_config, init_db, Base
from app.models import User, InviteToken, Workspace, Folder, Material, Session, Message
from app.config import load_config


async def drop_all_tables():
    """删除所有表"""
    print("正在删除所有旧表...")
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    print("旧表删除完成")


async def create_all_tables():
    """创建所有表"""
    print("正在创建新表...")
    await init_db()
    print("新表创建完成")
    print("\n创建的表:")
    print("- users (用户表)")
    print("- invite_tokens (邀请码表)")
    print("- workspaces (工作空间表)")
    print("- folders (文件夹表)")
    print("- materials (素材表)")
    print("- sessions (会话表)")
    print("- messages (消息表)")


async def insert_test_data():
    """插入测试数据"""
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.auth import hash_password
    
    print("\n正在插入测试数据...")
    
    async with AsyncSession(database.engine) as session:
        async with session.begin():
            # 创建测试用户
            test_user = User(
                username="testuser",
                email="test@example.com",
                password_hash=hash_password("testpass123"),
                is_active=True
            )
            session.add(test_user)
            await session.flush()
            print(f"✓ 创建测试用户: {test_user.username} (ID: {test_user.id})")
            
            # 创建邀请码
            invite = InviteToken(
                token="TEST2024",
                max_uses=10,
                used_count=0,
                created_by=test_user.id,
                is_active=True
            )
            session.add(invite)
            await session.flush()
            print(f"✓ 创建邀请码: {invite.token} (ID: {invite.id})")
            
            # 创建工作空间
            workspace1 = Workspace(
                user_id=test_user.id,
                name="我的第一个工作空间",
                description="这是一个测试工作空间"
            )
            session.add(workspace1)
            await session.flush()
            print(f"✓ 创建工作空间: {workspace1.name} (ID: {workspace1.id})")
            
            # 创建文件夹
            folder1 = Folder(
                workspace_id=workspace1.id,
                parent_id=None,
                name="项目文档"
            )
            session.add(folder1)
            await session.flush()
            print(f"✓ 创建文件夹: {folder1.name} (ID: {folder1.id})")
            
            # 创建子文件夹
            subfolder1 = Folder(
                workspace_id=workspace1.id,
                parent_id=folder1.id,
                name="会议记录"
            )
            session.add(subfolder1)
            await session.flush()
            print(f"✓ 创建子文件夹: {subfolder1.name} (ID: {subfolder1.id})")
            
            # 创建素材
            material1 = Material(
                workspace_id=workspace1.id,
                folder_id=folder1.id,
                user_id=test_user.id,
                title="项目需求文档",
                type="text",
                raw_content="这是项目需求的详细说明...",
                is_searchable=True
            )
            session.add(material1)
            await session.flush()
            print(f"✓ 创建素材: {material1.title} (ID: {material1.id})")
            
            # 创建会话（绑定到工作空间）
            session1 = Session(
                user_id=test_user.id,
                workspace_id=workspace1.id,
                title="项目讨论",
                model_id="gpt-4"
            )
            session.add(session1)
            await session.flush()
            print(f"✓ 创建会话: {session1.title} (ID: {session1.id})")
            
            # 创建消息
            msg1 = Message(
                session_id=session1.id,
                role="user",
                content="你好，我想讨论一下项目需求"
            )
            session.add(msg1)
            
            msg2 = Message(
                session_id=session1.id,
                role="assistant",
                content="你好！我很乐意帮助你讨论项目需求。请告诉我具体的问题。"
            )
            session.add(msg2)
            await session.flush()
            print(f"✓ 创建消息: 2条对话记录")
            
            # 创建独立会话（不绑定工作空间）
            session2 = Session(
                user_id=test_user.id,
                workspace_id=None,
                title="自由对话",
                model_id="gpt-3.5-turbo"
            )
            session.add(session2)
            await session.flush()
            print(f"✓ 创建独立会话: {session2.title} (ID: {session2.id})")
    
    print("\n测试数据插入完成！")


async def verify_data():
    """验证数据"""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession
    
    print("\n正在验证数据...")
    
    async with AsyncSession(database.engine) as session:
        # 验证用户数量
        result = await session.execute(select(User))
        users = result.scalars().all()
        print(f"✓ 用户数量: {len(users)}")
        
        # 验证工作空间
        result = await session.execute(select(Workspace))
        workspaces = result.scalars().all()
        print(f"✓ 工作空间数量: {len(workspaces)}")
        
        # 验证文件夹（包含层级）
        result = await session.execute(select(Folder))
        folders = result.scalars().all()
        print(f"✓ 文件夹数量: {len(folders)}")
        
        # 验证素材
        result = await session.execute(select(Material))
        materials = result.scalars().all()
        print(f"✓ 素材数量: {len(materials)}")
        
        # 验证会话
        result = await session.execute(select(Session))
        sessions = result.scalars().all()
        print(f"✓ 会话数量: {len(sessions)}")
        
        # 验证消息
        result = await session.execute(select(Message))
        messages = result.scalars().all()
        print(f"✓ 消息数量: {len(messages)}")
        
        print("\n数据验证完成！所有表结构正常。")


async def main():
    """主函数"""
    print("=" * 60)
    print("数据库初始化和测试脚本")
    print("=" * 60)
    
    # 加载配置 - 显式指定配置文件路径
    config_path = Path(__file__).parent / "config.toml"
    config = load_config(config_path)
    
    # 初始化数据库连接 - 使用正确的属性名
    database_url = f"mysql+aiomysql://{config.mysql.username}:{config.mysql.password}@{config.mysql.address}:{config.mysql.port}/{config.mysql.database}?charset=utf8mb4"
    init_database_config(database_url)
    
    try:
        # 1. 删除旧表
        await drop_all_tables()
        
        # 2. 创建新表
        await create_all_tables()
        
        # 3. 插入测试数据
        await insert_test_data()
        
        # 4. 验证数据
        await verify_data()
        
        print("\n" + "=" * 60)
        print("✅ 数据库初始化和测试完成！")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
