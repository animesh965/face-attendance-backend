from datetime import datetime, timezone

from bson import ObjectId

from app.core.database import get_database
from app.schemas.auth import UserRole


class UserModel:

    COLLECTION = "users"

    # ---------------------------------------------------------
    # Find user by email
    # ---------------------------------------------------------

    @staticmethod
    async def find_by_email(email: str):
        db = get_database()

        return await db[UserModel.COLLECTION].find_one({
            "email": email.lower().strip()
        })

    # ---------------------------------------------------------
    # Find user by ID
    # ---------------------------------------------------------

    @staticmethod
    async def find_by_id(user_id: str):
        db = get_database()

        return await db[UserModel.COLLECTION].find_one({
            "_id": ObjectId(user_id)
        })

    # ---------------------------------------------------------
    # Create user
    #
    # IMPORTANT:
    # Every signup user starts as "user".
    # Admin/Super Admin are NOT created from frontend signup.
    # ---------------------------------------------------------

    @staticmethod
    async def create(
        name: str,
        email: str,
        password_hash: str,
    ):
        db = get_database()

        now = datetime.now(timezone.utc)

        result = await db[UserModel.COLLECTION].insert_one({
            "name": name.strip(),
            "email": email.lower().strip(),
            "password_hash": password_hash,

            # Backend-controlled role
            "role": UserRole.USER.value,

            "is_active": True,

            # Employee information will be added later
            # by admin/super_admin during face registration.
            "employee_id": None,
            "phone": None,
            "department_id": None,
            "designation_id": None,
            "face_registered": False,

            "created_at": now,
            "updated_at": now,
        })

        return str(result.inserted_id)

    # ---------------------------------------------------------
    # Get users available for admin face registration
    # ---------------------------------------------------------

    @staticmethod
    async def get_users_for_registration():
        db = get_database()

        cursor = db[UserModel.COLLECTION].find(
            {
                "role": UserRole.USER.value,
                "is_active": True,
            },
            {
                "password_hash": 0,
                "phone": 0,
            }
        ).sort("name", 1)

        return await cursor.to_list(length=None)

    # ---------------------------------------------------------
    # Generate employee ID
    # Example:
    # EMP-1001
    # EMP-1002
    # EMP-1003
    # ---------------------------------------------------------

    @staticmethod
    async def generate_employee_id():
        db = get_database()

        last_user = await db[
            UserModel.COLLECTION
        ].find_one(
            {
                "employee_id": {
                    "$regex": r"^EMP-[0-9]+$"
                }
            },
            sort=[
                ("employee_id", -1)
            ],
        )

        if not last_user:
            return "EMP-1001"

        last_employee_id = last_user.get(
            "employee_id"
        )

        if not last_employee_id:
            return "EMP-1001"

        try:
            last_number = int(
                last_employee_id.replace(
                    "EMP-",
                    ""
                )
            )
        except ValueError:
            return "EMP-1001"

        return f"EMP-{last_number + 1}"

    # ---------------------------------------------------------
    # Update employee information
    # ---------------------------------------------------------

    @staticmethod
    async def update_employee_details(
        user_id: str,
        phone: str,
        department_id: str,
        designation_id: str,
    ):
        db = get_database()
    
        now = datetime.now(timezone.utc)
    
        # Generate employee ID on backend
        employee_id = await UserModel.generate_employee_id()
    
        result = await db[
            UserModel.COLLECTION
        ].update_one(
            {
                "_id": ObjectId(user_id),
                "role": UserRole.USER.value,
            },
            {
                "$set": {
                    "employee_id": employee_id,
                    "phone": phone,
                    "department_id": ObjectId(
                        department_id
                    ),
                    "designation_id": ObjectId(
                        designation_id
                    ),
                    "updated_at": now,
                }
            }
        )
    
        if result.matched_count == 0:
            return None
    
        return await UserModel.find_by_id(
            user_id
        )
    

    # ---------------------------------------------------------
    # Mark face as registered
    # ---------------------------------------------------------

    @staticmethod
    async def mark_face_registered(
        user_id: str,
    ):
        db = get_database()

        await db[
            UserModel.COLLECTION
        ].update_one(
            {
                "_id": ObjectId(user_id)
            },
            {
                "$set": {
                    "face_registered": True,
                    "updated_at": datetime.now(
                        timezone.utc
                    ),
                }
            }
        )























# from datetime import datetime

# from app.core.database import get_database
# from app.schemas.auth import UserRole

# from bson import ObjectId


# class UserModel:

#     COLLECTION = "users"

#     @staticmethod
#     async def find_by_email(email: str):
#         db = get_database()

#         return await db[UserModel.COLLECTION].find_one({
#             "email": email
#         })

#     @staticmethod
#     async def find_by_id(user_id: str):
#         db = get_database()

#         return await db[UserModel.COLLECTION].find_one({
#             "_id": ObjectId(user_id)
#         })

#     @staticmethod
#     async def create(
#         name: str,
#         email: str,
#         password_hash: str,
#     ):
#         db = get_database()

#         result = await db[UserModel.COLLECTION].insert_one({
#             "name": name,
#             "email": email,
#             "password_hash": password_hash,

#             # Backend-controlled default role
#             "role": UserRole.USER.value,

#             "is_active": True,
#             "created_at": datetime.utcnow(),
#         })

#         return str(result.inserted_id)

#     @staticmethod
#     async def get_users_for_registration():
#         db = get_database()
    
#         cursor = db[UserModel.COLLECTION].find(
#             {
#                 "role": "user",
#                 "is_active": True,
#             }
#         ).sort("name", 1)
    
#         return await cursor.to_list(length=None)

#     @staticmethod
#     async def update_employee_details(
#         user_id: str,
#         employee_id: str,
#         phone: str,
#         department_id: str,
#         designation_id: str,
#     ):
#         db = get_database()
    
#         now = datetime.now(timezone.utc)
    
#         result = await db[UserModel.COLLECTION].update_one(
#             {
#                 "_id": ObjectId(user_id)
#             },
#             {
#                 "$set": {
#                     "employee_id": employee_id,
#                     "phone": phone,
#                     "department_id": ObjectId(
#                         department_id
#                     ),
#                     "designation_id": ObjectId(
#                         designation_id
#                     ),
#                     "updated_at": now,
#                 }
#             }
#         )
    
#         if result.matched_count == 0:
#             return None
    
#         return await UserModel.find_by_id(user_id)
    


























# from datetime import datetime

# from app.core.database import get_database
# from bson import ObjectId
# from app.models.auth_model import UserRole


# class UserModel:

#     COLLECTION = "users"


#     @staticmethod
#     async def find_by_email(email: str):
#         db = get_database()

#         return await db[UserModel.COLLECTION].find_one({
#             "email": email
#         })

#     @staticmethod
#     async def find_by_id(user_id: str):
#         db = get_database()
    
#         return await db[UserModel.COLLECTION].find_one({
#             "_id": ObjectId(user_id)
#         })

#     @staticmethod
#         async def create(
#             name: str,
#             email: str,
#             password_hash: str,
#         ):
#             db = get_database()
    
#             result = await db[UserModel.COLLECTION].insert_one({
#                 "name": name,
#                 "email": email,
#                 "password_hash": password_hash,
    
#                 # Backend-controlled default role
#                 "role": UserRole.USER.value,
    
#                 "is_active": True,
#                 "created_at": datetime.utcnow(),
#             })
    
#             return str(result.inserted_id)

#     # @staticmethod
#     # async def create(name: str, email: str):
#     #     db = get_database()

#     #     result = await db[UserModel.COLLECTION].insert_one({
#     #         "name": name,
#     #         "email": email,
#     #         "created_at": datetime.utcnow()
#     #     })

#     #     return str(result.inserted_id)
