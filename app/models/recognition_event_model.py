from datetime import datetime

from app.core.database import get_database


class RecognitionEventModel:

    COLLECTION = "recognition_events"

    @staticmethod
    async def create(document: dict):

        db = get_database()

        result = await db[
            RecognitionEventModel.COLLECTION
        ].insert_one(document)

        document["_id"] = result.inserted_id

        return document

    @staticmethod
    async def count_today(
        start,
        end
    ):

        db = get_database()

        return await db[
            RecognitionEventModel.COLLECTION
        ].count_documents({
            "created_at": {
                "$gte": start,
                "$lt": end
            }
        })

    @staticmethod
    async def count_recognized_today(
        start,
        end
    ):

        db = get_database()

        return await db[
            RecognitionEventModel.COLLECTION
        ].count_documents({
            "created_at": {
                "$gte": start,
                "$lt": end
            },
            "recognized": True
        })

    @staticmethod
    async def count_unknown_today(
        start,
        end
    ):

        db = get_database()

        return await db[
            RecognitionEventModel.COLLECTION
        ].count_documents({
            "created_at": {
                "$gte": start,
                "$lt": end
            },
            "recognized": False
        })

    @staticmethod
    async def recent(
        start,
        end,
        limit=10
    ):

        db = get_database()

        cursor = (
            db[
                RecognitionEventModel.COLLECTION
            ]
            .find({
                "created_at": {
                    "$gte": start,
                    "$lt": end
                }
            })
            .sort(
                "created_at",
                -1
            )
            .limit(limit)
        )

        return await cursor.to_list(
            length=limit
        )
