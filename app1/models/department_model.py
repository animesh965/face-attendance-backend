from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from app.core.database import get_database


class DepartmentModel:

    COLLECTION = "departments"

    @staticmethod
    def _object_id(department_id: str) -> ObjectId:
        """
        Convert string ID to ObjectId.
        Raises ValueError for invalid IDs.
        """
        try:
            return ObjectId(department_id)
        except (InvalidId, TypeError):
            raise ValueError("Invalid department ID.")

    @staticmethod
    async def find_by_id(department_id: str):
        db = get_database()

        object_id = DepartmentModel._object_id(department_id)

        return await db[
            DepartmentModel.COLLECTION
        ].find_one({
            "_id": object_id
        })

    @staticmethod
    async def find_by_name(name: str):
        db = get_database()

        clean_name = name.strip()

        if not clean_name:
            return None

        normalized_name = clean_name.lower()

        return await db[
            DepartmentModel.COLLECTION
        ].find_one({
            "normalized_name": normalized_name,
            "is_active": True,
        })

    @staticmethod
    async def get_all():
        db = get_database()

        cursor = db[
            DepartmentModel.COLLECTION
        ].find({
            "is_active": True
        }).sort("name", 1)

        return await cursor.to_list(length=None)

    @staticmethod
    async def create(
        name: str,
        code: str,
    ):
        db = get_database()

        clean_name = name.strip()
        clean_code = code.strip().upper()

        if not clean_name:
            raise ValueError("Department name is required.")

        if not clean_code:
            raise ValueError("Department code is required.")

        now = datetime.now(timezone.utc)

        department = {
            "name": clean_name,
            "normalized_name": clean_name.lower(),
            "code": clean_code,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }

        result = await db[
            DepartmentModel.COLLECTION
        ].insert_one(department)

        department["_id"] = result.inserted_id

        return department



























# from datetime import datetime, timezone

# from bson import ObjectId

# from app.core.database import get_database


# class DepartmentModel:

#     COLLECTION = "departments"

#     @staticmethod
#     async def find_by_id(department_id: str):
#         db = get_database()

#         return await db[
#             DepartmentModel.COLLECTION
#         ].find_one({
#             "_id": ObjectId(department_id)
#         })

#     @staticmethod
#     async def find_by_name(name: str):
#         db = get_database()

#         return await db[DepartmentModel.COLLECTION].find_one({
#             "name": name.strip()
#         })

#     @staticmethod
#     async def get_all():
#         db = get_database()

#         cursor = db[DepartmentModel.COLLECTION].find(
#             {"is_active": True}
#         ).sort("name", 1)

#         return await cursor.to_list(length=None)

#     @staticmethod
#     async def create(name: str, code: str):
#         db = get_database()

#         now = datetime.now(timezone.utc)

#         department = {
#             "name": name.strip(),
#             "code": code.strip().upper(),
#             "is_active": True,
#             "created_at": now,
#             "updated_at": now,
#         }

#         result = await db[
#             DepartmentModel.COLLECTION
#         ].insert_one(department)

#         department["_id"] = result.inserted_id

#         return department


















# from datetime import datetime, timezone

# from app.core.database import get_database


# class DepartmentModel:

#     COLLECTION = "departments"

#     @staticmethod
#     async def find_by_id(department_id: str):
#         db = get_database()

#         return await db[DepartmentModel.COLLECTION].find_one({
#             "_id": department_id
#         })

#     @staticmethod
#     async def find_by_name(name: str):
#         db = get_database()

#         return await db[DepartmentModel.COLLECTION].find_one({
#             "name": name.strip()
#         })

#     @staticmethod
#     async def get_all():
#         db = get_database()

#         cursor = db[DepartmentModel.COLLECTION].find(
#             {"is_active": True}
#         ).sort("name", 1)

#         return await cursor.to_list(length=None)

#     @staticmethod
#     async def create(name: str, code: str):
#         db = get_database()

#         now = datetime.now(timezone.utc)

#         department = {
#             "name": name.strip(),
#             "code": code.strip().upper(),
#             "is_active": True,
#             "created_at": now,
#             "updated_at": now,
#         }

#         result = await db[
#             DepartmentModel.COLLECTION
#         ].insert_one(department)

#         department["_id"] = result.inserted_id

#         return department
