from datetime import datetime

from app.core.database import get_database


class AttendanceModel:

    COLLECTION = "attendance"

    # ==================================================
    # FIND ONE USER FOR ONE DATE
    # ==================================================

    @staticmethod
    async def find_by_user_and_date(
        user_id: str,
        date: str
    ):

        db = get_database()

        return await db[
            AttendanceModel.COLLECTION
        ].find_one({
            "user_id": user_id,
            "date": date
        })

    # ==================================================
    # FIND TODAY FOR ONE USER
    # ==================================================

    @staticmethod
    async def find_today_by_user(
        user_id: str,
        date: str
    ):

        return await AttendanceModel.find_by_user_and_date(
            user_id=user_id,
            date=date
        )

    # ==================================================
    # CREATE
    # ==================================================

    @staticmethod
    async def create(document: dict):

        db = get_database()

        result = await db[
            AttendanceModel.COLLECTION
        ].insert_one(document)

        document["_id"] = result.inserted_id

        return document

    # ==================================================
    # CHECK OUT
    # ==================================================

    @staticmethod
    async def check_out(
        attendance_id,
        check_out: datetime
    ):

        db = get_database()

        await db[
            AttendanceModel.COLLECTION
        ].update_one(
            {
                "_id": attendance_id
            },
            {
                "$set": {
                    "check_out": check_out,
                    "updated_at": check_out
                }
            }
        )

    # ==================================================
    # FIND ALL ATTENDANCE FOR DATE
    # ==================================================

    @staticmethod
    async def find_today(
        date: str
    ):

        db = get_database()

        cursor = (
            db[
                AttendanceModel.COLLECTION
            ]
            .find({
                "date": date
            })
            .sort(
                "check_in",
                1
            )
        )

        return await cursor.to_list(
            length=None
        )

    # ==================================================
    # FIND USER ATTENDANCE FOR MONTH
    # ==================================================

    @staticmethod
    async def find_by_user_and_month(
        user_id: str,
        start_date: str,
        end_date: str
    ):

        db = get_database()

        cursor = (
            db[
                AttendanceModel.COLLECTION
            ]
            .find({
                "user_id": user_id,
                "date": {
                    "$gte": start_date,
                    "$lt": end_date
                }
            })
            .sort(
                "date",
                1
            )
        )

        return await cursor.to_list(
            length=None
        )

    # ==================================================
    # FIND ALL ATTENDANCE FOR DATE RANGE
    # ==================================================

    @staticmethod
    async def find_by_date_range(
        start_date: str,
        end_date: str
    ):

        db = get_database()

        cursor = (
            db[
                AttendanceModel.COLLECTION
            ]
            .find({
                "date": {
                    "$gte": start_date,
                    "$lt": end_date
                }
            })
            .sort(
                [
                    ("date", 1),
                    ("check_in", 1)
                ]
            )
        )

        return await cursor.to_list(
            length=None
        )


































# from datetime import datetime

# from app.core.database import get_database


# class AttendanceModel:

#     COLLECTION = "attendance"

#     @staticmethod
#     async def find_by_user_and_date(
#         user_id: str,
#         date: str
#     ):
#         db = get_database()

#         return await db[AttendanceModel.COLLECTION].find_one({
#             "user_id": user_id,
#             "date": date
#         })


#     @staticmethod
#     async def find_today_by_user(
#         user_id: str,
#         date: str
#     ):
#         return await AttendanceModel.find_by_user_and_date(
#             user_id=user_id,
#             date=date
#         )

#     @staticmethod
#     async def create(document: dict):

#         db = get_database()

#         result = await db[
#             AttendanceModel.COLLECTION
#         ].insert_one(document)

#         document["_id"] = result.inserted_id

#         return document

#     @staticmethod
#     async def check_out(
#         attendance_id,
#         check_out: datetime
#     ):

#         db = get_database()

#         await db[
#             AttendanceModel.COLLECTION
#         ].update_one(
#             {
#                 "_id": attendance_id
#             },
#             {
#                 "$set": {
#                     "check_out": check_out,
#                     "updated_at": check_out
#                 }
#             }
#         )

#     # ==================================================
#     # FIND TODAY FOR ONE USER
#     # ==================================================

#     @staticmethod
#     async def find_today_by_user(
#         user_id: str,
#         date: str
#     ):

#         db = get_database()

#         return await db[
#             AttendanceModel.COLLECTION
#         ].find_one({
#             "user_id": user_id,
#             "date": date
#         })

#     # ==================================================
#     # FIND ALL ATTENDANCE FOR A DATE
#     # ==================================================

#     @staticmethod
#     async def find_today(
#         date: str
#     ):

#         db = get_database()

#         cursor = (
#             db[
#                 AttendanceModel.COLLECTION
#             ]
#             .find({
#                 "date": date
#             })
#             .sort(
#                 "check_in",
#                 1
#             )
#         )

#         return await cursor.to_list(
#             length=None
#         )

#     # ==================================================
#     # FIND USER ATTENDANCE FOR MONTH
#     # ==================================================

#     @staticmethod
#     async def find_by_user_and_month(
#         user_id: str,
#         start_date: str,
#         end_date: str
#     ):

#         db = get_database()

#         cursor = (
#             db[
#                 AttendanceModel.COLLECTION
#             ]
#             .find({
#                 "user_id": user_id,

#                 "date": {
#                     "$gte": start_date,
#                     "$lt": end_date
#                 }
#             })
#             .sort(
#                 "date",
#                 1
#             )
#         )

#         return await cursor.to_list(
#             length=None
#         )

#     # ==================================================
#     # FIND ALL ATTENDANCE FOR DATE RANGE
#     # ==================================================

#     @staticmethod
#     async def find_by_date_range(
#         start_date: str,
#         end_date: str
#     ):

#         db = get_database()

#         cursor = (
#             db[
#                 AttendanceModel.COLLECTION
#             ]
#             .find({
#                 "date": {
#                     "$gte": start_date,
#                     "$lt": end_date
#                 }
#             })
#             .sort(
#                 "date",
#                 1
#             )
#         )

#         return await cursor.to_list(
#             length=None
#         )

#     @staticmethod
#     async def find_by_date(
#         date: str,
#         limit: int = 100
#     ):

#         db = get_database()

#         cursor = (
#             db[AttendanceModel.COLLECTION]
#             .find({
#                 "date": date
#             })
#             .sort(
#                 "check_in",
#                 -1
#             )
#             .limit(limit)
#         )

#         return await cursor.to_list(
#             length=limit
#         )

#     @staticmethod
#     async def count_by_date(
#         date: str
#     ):

#         db = get_database()

#         return await db[
#             AttendanceModel.COLLECTION
#         ].count_documents({
#             "date": date
#         })























# # from datetime import datetime

# # from app.core.database import get_database


# # class AttendanceModel:

# #     COLLECTION = "attendance"

# #     @staticmethod
# #     async def find_by_user_and_date(
# #         user_id: str,
# #         date: str
# #     ):
# #         db = get_database()

# #         return await db[AttendanceModel.COLLECTION].find_one({
# #             "user_id": user_id,
# #             "date": date
# #         })


# #     @staticmethod
# #     async def find_today_by_user(
# #         user_id: str,
# #         date: str
# #     ):
# #         return await AttendanceModel.find_by_user_and_date(
# #             user_id=user_id,
# #             date=date
# #         )

# #     @staticmethod
# #     async def create(document: dict):

# #         db = get_database()

# #         result = await db[
# #             AttendanceModel.COLLECTION
# #         ].insert_one(document)

# #         document["_id"] = result.inserted_id

# #         return document

# #     @staticmethod
# #     async def check_out(
# #         attendance_id,
# #         check_out: datetime
# #     ):

# #         db = get_database()

# #         await db[
# #             AttendanceModel.COLLECTION
# #         ].update_one(
# #             {
# #                 "_id": attendance_id
# #             },
# #             {
# #                 "$set": {
# #                     "check_out": check_out,
# #                     "updated_at": check_out
# #                 }
# #             }
# #         )

# #     # ==================================================
# #         # FIND TODAY FOR ONE USER
# #         # ==================================================
    
# #     @staticmethod
# #     async def find_today_by_user(
# #             user_id: str,
# #             date: str
# #         ):
    
# #             db = get_database()
    
# #             return await db[
# #                 AttendanceModel.COLLECTION
# #             ].find_one({
# #                 "user_id": user_id,
# #                 "date": date
# #             })
    
# #         # ==================================================
# #         # FIND ALL ATTENDANCE FOR A DATE
# #         # ==================================================
    
# #     @staticmethod
# #     async def find_today(
# #             date: str
# #         ):
    
# #             db = get_database()
    
# #             cursor = (
# #                 db[
# #                     AttendanceModel.COLLECTION
# #                 ]
# #                 .find({
# #                     "date": date
# #                 })
# #                 .sort(
# #                     "check_in",
# #                     1
# #                 )
# #             )
    
# #             return await cursor.to_list(
# #                 length=None
# #             )
    
# #         # ==================================================
# #         # FIND USER ATTENDANCE FOR MONTH
# #         # ==================================================
    
# #     @staticmethod
# #     async def find_by_user_and_month(
# #             user_id: str,
# #             start_date: str,
# #             end_date: str
# #         ):
    
# #             db = get_database()
    
# #             cursor = (
# #                 db[
# #                     AttendanceModel.COLLECTION
# #                 ]
# #                 .find({
# #                     "user_id": user_id,
    
# #                     "date": {
# #                         "$gte": start_date,
# #                         "$lt": end_date
# #                     }
# #                 })
# #                 .sort(
# #                     "date",
# #                     1
# #                 )
# #             )
    
# #             return await cursor.to_list(
# #                 length=None
# #             )
    
# #         # ==================================================
# #         # FIND ALL ATTENDANCE FOR DATE RANGE
# #         # ==================================================
    
# #     @staticmethod
# #     async def find_by_date_range(
# #         start_date: str,
# #         end_date: str
# #     ):
    
# #         db = get_database()
    
# #         cursor = (
# #                 db[
# #                     AttendanceModel.COLLECTION
# #                 ]
# #                 .find({
# #                     "date": {
# #                         "$gte": start_date,
# #                         "$lt": end_date
# #                     }
# #                 })
# #                 .sort(
# #                     "date",
# #                     1
# #                 )
# #         )
    
# #         return await cursor.to_list(
# #             length=None
# #         )

# #     @staticmethod
# #     async def find_by_date(
# #         date: str,
# #         limit: int = 100
# #     ):

# #         db = get_database()

# #         cursor = (
# #             db[AttendanceModel.COLLECTION]
# #             .find({
# #                 "date": date
# #             })
# #             .sort(
# #                 "check_in",
# #                 -1
# #             )
# #             .limit(limit)
# #         )

# #         return await cursor.to_list(
# #             length=limit
# #         )

# #     @staticmethod
# #     async def count_by_date(
# #         date: str
# #     ):

# #         db = get_database()

# #         return await db[
# #             AttendanceModel.COLLECTION
# #         ].count_documents({
# #             "date": date
# #         })

    
