from app.core.database import get_database
from pymongo import ReturnDocument


class CounterModel:

    COLLECTION = "counters"

    @staticmethod
    async def get_next_employee_id():

        db = get_database()

        counter = await db[
            CounterModel.COLLECTION
        ].find_one_and_update(
            {
                "_id": "employee_id"
            },
            {
                "$inc": {
                    "sequence": 1
                }
            },
            upsert=True,
            return_document=ReturnDocument.AFTER
        )

        sequence = counter["sequence"]

        return f"EMP-{sequence:05d}"
