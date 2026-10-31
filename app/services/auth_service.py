from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.core.security import (
    hash_password,
    verify_password,
)
from app.schemas.auth import SignupRequest, UserRole


async def get_user_by_email(
    users_collection,
    email: str,
):
    """
    Find user by email.
    """

    return await users_collection.find_one(
        {
            "email": email.lower().strip()
        }
    )


async def create_user(
    users_collection,
    data: SignupRequest,
):
    """
    Create a new user.

    Every new signup starts with the USER role.
    Employee information is added later by
    an admin or super_admin during face registration.
    """

    email = data.email.lower().strip()

    # ---------------------------------------------------------
    # Check if email is already registered
    # ---------------------------------------------------------

    existing_user = await get_user_by_email(
        users_collection,
        email,
    )

    if existing_user:
        raise ValueError(
            "Email already registered"
        )

    # ---------------------------------------------------------
    # Every new signup is ALWAYS a normal user
    # ---------------------------------------------------------

    role = UserRole.USER.value

    # ---------------------------------------------------------
    # Current UTC time
    # ---------------------------------------------------------

    now = datetime.now(timezone.utc)

    # ---------------------------------------------------------
    # Create user document
    # ---------------------------------------------------------

    user = {
        "name": data.name.strip(),
        "email": email,

        "password_hash": hash_password(
            data.password
        ),

        # Backend controlled
        "role": role,

        "is_active": True,

        # -----------------------------------------------------
        # Employee information
        #
        # These are empty when the user signs up.
        # Admin/Super Admin will fill these during
        # face registration.
        # -----------------------------------------------------

        "employee_id": None,
        "phone": None,
        "department_id": None,
        "designation_id": None,

        # -----------------------------------------------------
        # Face registration status
        # -----------------------------------------------------

        "face_registered": False,

        "created_at": now,
        "updated_at": now,
    }

    try:
        result = await users_collection.insert_one(
            user
        )

    except DuplicateKeyError:
        raise ValueError(
            "Email already registered"
        )

    # Add MongoDB generated ID
    user["_id"] = result.inserted_id

    return user


async def authenticate_user(
    users_collection,
    email: str,
    password: str,
):
    """
    Authenticate user using email and password.
    """

    # Find user
    user = await get_user_by_email(
        users_collection,
        email,
    )

    # User does not exist
    if not user:
        return None

    # Verify password
    if not verify_password(
        password,
        user["password_hash"],
    ):
        return None

    # Check whether account is active
    if not user.get(
        "is_active",
        True,
    ):
        return None

    return user


























# from datetime import datetime, timezone

# from pymongo.errors import DuplicateKeyError

# from app.core.security import (
#     hash_password,
#     verify_password,
# )
# from app.schemas.auth import SignupRequest, UserRole


# async def get_user_by_email(
#     users_collection,
#     email: str,
# ):
#     """
#     Find user by email.
#     """

#     return await users_collection.find_one(
#         {
#             "email": email.lower().strip()
#         }
#     )


# async def create_user(
#     users_collection,
#     data: SignupRequest,
# ):
#     """
#     Create a new user.

#     Every new user starts with the USER role.
#     """

#     email = data.email.lower().strip()

#     # Check if email is already registered
#     existing_user = await get_user_by_email(
#         users_collection,
#         email,
#     )

#     if existing_user:
#         raise ValueError(
#             "Email already registered"
#         )

#     # Every new user starts as a normal user
#     role = UserRole.USER.value

#     # Current UTC time
#     now = datetime.now(timezone.utc)

#     # Create user document
#     user = {
#         "name": data.name.strip(),
#         "email": email,
#         "password_hash": hash_password(
#             data.password
#         ),
#         "role": role,
#         "is_active": True,
#         "created_at": now,
#         "updated_at": now,
#     }

#     try:
#         result = await users_collection.insert_one(
#             user
#         )

#     except DuplicateKeyError:
#         raise ValueError(
#             "Email already registered"
#         )

#     # Add MongoDB generated ID
#     user["_id"] = result.inserted_id

#     return user


# async def authenticate_user(
#     users_collection,
#     email: str,
#     password: str,
# ):
#     """
#     Authenticate user using email and password.
#     """

#     # Find user
#     user = await get_user_by_email(
#         users_collection,
#         email,
#     )

#     # User does not exist
#     if not user:
#         return None

#     # Verify password
#     if not verify_password(
#         password,
#         user["password_hash"],
#     ):
#         return None

#     # Check whether account is active
#     if not user.get(
#         "is_active",
#         True,
#     ):
#         return None

#     return user
 