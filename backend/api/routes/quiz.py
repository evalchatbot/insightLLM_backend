from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict
import os
import random
from backend.db.supabase_service import SupabaseService

router = APIRouter(prefix="/quiz", tags=["quiz"])

# Use the same SupabaseService as other routes
db_service = SupabaseService(
    supabase_url=os.getenv("SUPABASE_URL"),
    supabase_key=os.getenv("SUPABASE_KEY")
)

@router.get("/mcqs", response_model=List[Dict])
def get_random_mcqs(genre_id: str = Query(..., description="Genre ID"), limit: int = 20):
    """Fetch MCQs for a genre and return up to `limit` random items.

    This endpoint filters by `genre_id` in the database, safely handles errors,
    and returns the `correct_answer` field so the frontend can calculate the score.
    """
    try:
        # Query Supabase for MCQs matching the genre_id
        result = db_service.supabase.table("mcqs").select(
            "id,question,option_a,option_b,option_c,option_d,correct_answer,genre_id"
        ).eq("genre_id", genre_id).execute()

        if hasattr(result, 'error') and result.error:
            raise Exception(f"Supabase query error: {result.error}")

        mcqs = result.data if result.data else []
        if not mcqs:
            raise HTTPException(status_code=404, detail="No MCQs found for this genre.")

        # Randomly select up to 'limit' MCQs
        selected = random.sample(mcqs, min(limit, len(mcqs)))

        # Return selected MCQs including correct_answer so frontend can grade
        return selected
    except HTTPException:
        raise
    except Exception as e:
        # Avoid printing secrets to stdout; log minimal info and return 500
        import traceback
        print(f"[QUIZ ERROR] {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to fetch MCQs")
