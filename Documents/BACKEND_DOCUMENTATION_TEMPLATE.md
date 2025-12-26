# Backend Documentation Template for Future Changes

This template should be used whenever making changes to the backend codebase. Follow this structure to ensure all changes are properly documented.

---

## Change Documentation Template

### Basic Information
```markdown
## Change: [Brief Description]

**Date**: [YYYY-MM-DD]
**Author**: [Your Name]
**Type**: [Feature/ Bug Fix/ Refactor/ Performance/ Documentation]
**Files Changed**: [List of files]
**Related Issues/PRs**: [Issue numbers or PR links]
```

### Detailed Description
```markdown
### What Changed?
[Describe what was changed and why]

### Why Was This Change Needed?
[Explain the problem or requirement that led to this change]

### How Does It Work?
[Explain the implementation approach]

### Breaking Changes
[If any, list breaking changes and migration steps]

### Testing
[Describe how to test the changes]
```

---

## API Route Change Template

When adding or modifying an API route:

```markdown
## API Route: [Method] /[route]

**Location**: `backend/api/routes/[route].py`

### Purpose
[What does this endpoint do?]

### Authentication
[Required/Optional - describe auth requirements]

### Request
**Method**: [GET/POST/PUT/DELETE]
**Body**:
```json
{
  // Request body structure
}
```

**Query Parameters**:
- `param1`: [Description]
- `param2`: [Description]

### Response
**Success (200)**:
```json
{
  // Response structure
}
```

**Error Responses**:
- `400`: [Description]
- `401`: [Description]
- `500`: [Description]

### Features
- [Feature 1]
- [Feature 2]

### Database Operations
[Describe any database queries or operations]

### Error Handling
[Describe error handling approach]

### Usage Example
```python
import requests

response = requests.post(
    'http://localhost:8000/api/route',
    json={...},
    headers={'Authorization': f'Bearer {token}'}
)
```
```

---

## Module/Agent Change Template

When adding or modifying a module or agent:

```markdown
## Module: [ModuleName]

**Location**: `backend/[module]/[file].py`

### Purpose
[What does this module do?]

### Class/Function: [Name]

**Parameters**:
```python
def function_name(param1: Type, param2: Type) -> ReturnType:
    """
    Description of function.
    
    Args:
        param1: Description
        param2: Description
    
    Returns:
        Description of return value
    
    Raises:
        ExceptionType: When this exception occurs
    """
```

### Features
- [Feature 1]
- [Feature 2]

### Dependencies
[List key dependencies and why they're needed]

### Usage Example
```python
from backend.module import ClassName

instance = ClassName()
result = instance.method(param1, param2)
```

### Notes
[Any important notes, gotchas, or future improvements]
```

---

## Database Change Template

When modifying database schema or operations:

```markdown
## Database Change: [Description]

**Date**: [YYYY-MM-DD]
**Type**: [Schema Change/ Migration/ Query Optimization]

### What Changed?
[Describe the database change]

### Migration
[If schema change, describe migration steps]

**SQL Migration**:
```sql
-- Migration SQL
```

### Affected Tables
- `table1`: [What changed]
- `table2`: [What changed]

### Backward Compatibility
[Describe compatibility considerations]

### Rollback Plan
[How to rollback if needed]
```

---

## Bug Fix Template

When fixing a bug:

```markdown
## Bug Fix: [Bug Description]

**Date**: [YYYY-MM-DD]
**Issue**: [Issue number or description]

### Problem
[Describe the bug and its symptoms]

### Root Cause
[Explain what caused the bug]

### Solution
[Describe how the bug was fixed]

### Files Changed
- `file1.py`: [What was changed]
- `file2.py`: [What was changed]

### Testing
[How to verify the fix works]

### Prevention
[How to prevent similar bugs in the future]
```

---

## Feature Addition Template

When adding a new feature:

```markdown
## Feature: [Feature Name]

**Date**: [YYYY-MM-DD]
**Status**: [In Progress/Completed]

### Description
[Describe the feature]

### User Story
[As a [user type], I want [goal] so that [benefit]]

### Implementation
[Describe the implementation approach]

### Modules Added/Modified
- `module1.py`: [Purpose]
- `module2.py`: [Purpose]

### API Routes Added/Modified
- `POST /api/route`: [Purpose]

### Database Changes
[If any, describe database changes]

### Testing
[How to test the feature]

### Future Improvements
[Planned enhancements or known limitations]
```

---

## Refactoring Template

When refactoring code:

```markdown
## Refactor: [What Was Refactored]

**Date**: [YYYY-MM-DD]
**Reason**: [Why was this refactored?]

### Before
[Describe the old implementation]

### After
[Describe the new implementation]

### Benefits
- [Benefit 1]
- [Benefit 2]

### Breaking Changes
[If any, list them]

### Migration Guide
[If needed, provide migration steps]
```

---

## Performance Optimization Template

When optimizing performance:

```markdown
## Performance: [Optimization Description]

**Date**: [YYYY-MM-DD]
**Impact**: [High/Medium/Low]

### Problem
[Describe the performance issue]

### Solution
[Describe the optimization]

### Metrics
- **Before**: [Metrics]
- **After**: [Metrics]
- **Improvement**: [Percentage or description]

### Changes Made
[Files and specific changes]

### Testing
[How to verify the improvement]
```

---

## Checklist for All Changes

Before committing changes, ensure:

- [ ] Code follows PEP 8 style guidelines
- [ ] Type hints are added to all functions
- [ ] Error handling is implemented
- [ ] Logging is added for important operations
- [ ] Documentation is updated
- [ ] Docstrings explain complex logic
- [ ] No hardcoded secrets or credentials
- [ ] Environment variables are documented (if new ones added)
- [ ] Breaking changes are documented
- [ ] Migration guide provided (if needed)
- [ ] Tests are written/updated
- [ ] API documentation is updated (if API changes)

---

## How to Use This Template

1. **Copy the relevant template** for your change type
2. **Fill in all sections** with relevant information
3. **Add the documentation** to the appropriate file:
   - API changes → Update `BACKEND_API_ROUTES_DOCUMENTATION.md`
   - Module changes → Update `BACKEND_MODULES_DOCUMENTATION.md`
   - New features → Add to `BACKEND_DOCUMENTATION.md` or create new doc
4. **Commit documentation** along with code changes
5. **Update "Last Updated"** date in main documentation files

---

## Documentation File Structure

```
Documents/
├── BACKEND_DOCUMENTATION.md              # Main overview and architecture
├── BACKEND_API_ROUTES_DOCUMENTATION.md   # All API routes
├── BACKEND_MODULES_DOCUMENTATION.md      # All modules and components
├── BACKEND_DOCUMENTATION_TEMPLATE.md     # This file
└── README.md                             # Documentation index
```

---

## Best Practices

1. **Document as you code** - Don't wait until the end
2. **Be specific** - Include code examples and file paths
3. **Explain why** - Not just what, but why decisions were made
4. **Keep it updated** - Update docs when code changes
5. **Use clear language** - Write for developers who aren't familiar with the code
6. **Include examples** - Code examples help understanding
7. **Link related docs** - Cross-reference related documentation
8. **Version information** - Note when changes were made

---

**Remember**: Good documentation saves time in the future and helps prevent bugs!

