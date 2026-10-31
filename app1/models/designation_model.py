from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from app.core.database import get_database


class DesignationModel:

    COLLECTION = "designations"

    @staticmethod
    def _object_id(designation_id: str) -> ObjectId:
        """
        Convert string ID to ObjectId.
        Raises ValueError for invalid IDs.
        """
        try:
            return ObjectId(designation_id)
        except (InvalidId, TypeError):
            raise ValueError("Invalid designation ID.")

    @staticmethod
    def _department_object_id(department_id: str) -> ObjectId:
        """
        Convert department string ID to ObjectId.
        Raises ValueError for invalid IDs.
        """
        try:
            return ObjectId(department_id)
        except (InvalidId, TypeError):
            raise ValueError("Invalid department ID.")

    @staticmethod
    async def find_by_id(designation_id: str):
        db = get_database()

        object_id = DesignationModel._object_id(
            designation_id
        )

        return await db[
            DesignationModel.COLLECTION
        ].find_one({
            "_id": object_id
        })

    @staticmethod
    async def find_by_name_and_department(
        name: str,
        department_id: str,
    ):
        db = get_database()

        clean_name = name.strip()

        if not clean_name:
            return None

        normalized_name = clean_name.lower()

        department_object_id = (
            DesignationModel._department_object_id(
                department_id
            )
        )

        return await db[
            DesignationModel.COLLECTION
        ].find_one({
            "normalized_name": normalized_name,
            "department_id": department_object_id,
            "is_active": True,
        })

    @staticmethod
    async def get_all():
        """
        Return all active designations.
        """
        db = get_database()

        cursor = db[
            DesignationModel.COLLECTION
        ].find({
            "is_active": True,
        }).sort("name", 1)

        return await cursor.to_list(length=None)

    @staticmethod
    async def get_by_department(
        department_id: str,
    ):
        """
        Return only active designations
        belonging to the specified department.
        """
        db = get_database()

        department_object_id = (
            DesignationModel._department_object_id(
                department_id
            )
        )

        cursor = db[
            DesignationModel.COLLECTION
        ].find({
            "department_id": department_object_id,
            "is_active": True,
        }).sort("name", 1)

        return await cursor.to_list(length=None)

    @staticmethod
    async def create(
        name: str,
        department_id: str,
    ):
        db = get_database()

        clean_name = name.strip()

        if not clean_name:
            raise ValueError("Designation name is required.")

        department_object_id = (
            DesignationModel._department_object_id(
                department_id
            )
        )

        now = datetime.now(timezone.utc)

        designation = {
            "name": clean_name,
            "normalized_name": clean_name.lower(),
            "department_id": department_object_id,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }

        result = await db[
            DesignationModel.COLLECTION
        ].insert_one(designation)

        designation["_id"] = result.inserted_id

        return designation
























# from datetime import datetime, timezone

# from bson import ObjectId

# from app.core.database import get_database


# class DesignationModel:

#     COLLECTION = "designations"


#     @staticmethod
#     async def find_by_name_and_department(
#         name: str,
#         department_id: str,
#     ):
#         db = get_database()
    
#         return await db[
#             DesignationModel.COLLECTION
#         ].find_one({
#             "name": name.strip(),
#             "department_id": ObjectId(department_id),
#             "is_active": True,
#         })
    

#     @staticmethod
#     async def find_by_id(designation_id: str):
#         db = get_database()

#         return await db[
#             DesignationModel.COLLECTION
#         ].find_one({
#             "_id": ObjectId(designation_id)
#         })

#     @staticmethod
#     async def get_all():
#         db = get_database()

#         cursor = db[
#             DesignationModel.COLLECTION
#         ].find({
#             "is_active": True,
#         }).sort("name", 1)

#         return await cursor.to_list(length=None)

#     @staticmethod
#     async def get_by_department(
#         department_id: str,
#     ):
#         db = get_database()

#         cursor = db[
#             DesignationModel.COLLECTION
#         ].find({
#             "department_id": ObjectId(department_id),
#             "is_active": True,
#         }).sort("name", 1)

#         return await cursor.to_list(length=None)

#     @staticmethod
#     async def create(
#         name: str,
#         department_id: str,
#     ):
#         db = get_database()

#         now = datetime.now(timezone.utc)

#         designation = {
#             "name": name.strip(),
#             "department_id": ObjectId(department_id),
#             "is_active": True,
#             "created_at": now,
#             "updated_at": now,
#         }

#         result = await db[
#             DesignationModel.COLLECTION
#         ].insert_one(designation)

#         designation["_id"] = result.inserted_id

#         return designation

























# from datetime import datetime, timezone

# from bson import ObjectId

# from app.core.database import get_database


# class DesignationModel:

#     COLLECTION = "designations"

#     @staticmethod
#     async def find_by_id(designation_id: str):
#         db = get_database()

#         return await db[
#             DesignationModel.COLLECTION
#         ].find_one({
#             "_id": ObjectId(designation_id)
#         })

#     @staticmethod
#     async def get_by_department(
#         department_id: str,
#     ):
#         db = get_database()

#         cursor = db[
#             DesignationModel.COLLECTION
#         ].find({
#             "department_id": ObjectId(department_id),
#             "is_active": True,
#         }).sort("name", 1)

#         return await cursor.to_list(length=None)

#     @staticmethod
#     async def create(
#         name: str,
#         department_id: str,
#     ):
#         db = get_database()

#         now = datetime.now(timezone.utc)

#         designation = {
#             "name": name.strip(),
#             "department_id": ObjectId(department_id),
#             "is_active": True,
#             "created_at": now,
#             "updated_at": now,
#         }

#         result = await db[
#             DesignationModel.COLLECTION
#         ].insert_one(designation)

#         designation["_id"] = result.inserted_id

#         return designation
