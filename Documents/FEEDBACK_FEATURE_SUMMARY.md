# Feedback Feature - Backend Implementation Summary

## Quick Reference

This is a summary document for the backend implementation of the feedback feature. For the complete plan, see `../insightLLM_frontend_2.0/FEEDBACK_FEATURE_PLAN.md`.

## Backend Requirements

### New Files to Create

1. **`backend/api/routes/feedback.py`**
   - Main feedback API route
   - Request/Response models
   - Validation and rate limiting

2. **`backend/utils/google_forms.py`** (Optional)
   - Google Forms API integration
   - Or Google Sheets API integration

### Files to Modify

1. **`backend/main.py`**
   - Add: `app.include_router(feedback.router)`

### Database Schema (Supabase)

**Table**: `feedback` or `user_feedback`

```sql
CREATE TABLE IF NOT EXISTS feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT,
    user_email TEXT,
    message TEXT NOT NULL,
    page_url TEXT,
    category TEXT DEFAULT 'general',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    status TEXT DEFAULT 'pending'
);

CREATE INDEX IF NOT EXISTS idx_feedback_user_id ON feedback(user_id);
CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON feedback(created_at);
```

### API Endpoint

**POST** `/feedback/submit`

**Request Model**:
```python
class FeedbackRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    userId: Optional[str] = None
    userEmail: Optional[str] = None
    pageUrl: Optional[str] = None
    category: Optional[str] = "general"
```

**Response Model**:
```python
class FeedbackResponse(BaseModel):
    success: bool
    message: str
    feedback_id: Optional[str] = None
```

### Rate Limiting

- **Per User/IP**: 3 submissions per hour
- **Per User/IP**: 10 submissions per day
- Use FastAPI rate limiting middleware or custom implementation

### Environment Variables

```bash
# Optional: Google Forms/Sheets
GOOGLE_FORMS_URL=<form_url>
GOOGLE_SHEETS_ID=<spreadsheet_id>
GOOGLE_SERVICE_ACCOUNT_KEY=<json_key_path>

# Rate Limiting
FEEDBACK_RATE_LIMIT_PER_HOUR=3
FEEDBACK_RATE_LIMIT_PER_DAY=10
```

### Implementation Steps

1. Create `feedback.py` route file
2. Define Pydantic models
3. Implement validation
4. Add rate limiting
5. Set up Supabase storage
6. Optional: Google Forms/Sheets integration
7. Register route in `main.py`
8. Test endpoint

### Error Handling

- **400**: Validation errors (empty message, too long)
- **429**: Rate limit exceeded
- **500**: Server errors (database, external API failures)

### Logging

Log all feedback submissions for analytics:
- User ID (if available)
- Timestamp
- Category
- Page URL
- Success/failure status

---

For complete implementation details, see the main plan document.

