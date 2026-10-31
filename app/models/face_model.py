from datetime import datetime

from app.core.database import get_database
from datetime import datetime, timezone



class FaceModel:

    COLLECTION = "face_embeddings"


    @staticmethod
    async def create(document: dict):
        db = get_database()

        result = await db[FaceModel.COLLECTION].insert_one({
            **document,
            "created_at": datetime.now(timezone.utc)

        })

        return str(result.inserted_id)


    @staticmethod
    async def get_faces_by_user(user_id: str):
        db = get_database()

        faces = await db[FaceModel.COLLECTION].find({
            "user_id": user_id
        }).to_list(length=None)

        return faces

    @staticmethod
    async def get_all_embeddings():
        db = get_database()
    
        faces = await db[FaceModel.COLLECTION].find(
            {},
            {
                "user_id": 1,
                "embedding": 1,
                "confidence": 1,
                "image_path": 1,
                "crop_path": 1,
            }
        ).to_list(length=None)
    
        return faces

    @staticmethod
    async def count_by_user_id(user_id: str):
        db = get_database()
    
        return await db[
            FaceModel.COLLECTION
        ].count_documents({
            "user_id": user_id
        })
    
