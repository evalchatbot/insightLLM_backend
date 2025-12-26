# Documentation Process Guide

**IMPORTANT**: All code changes must be documented. This is now a mandatory part of the development workflow.

---

## 📋 Quick Checklist

Before committing any changes, ensure:

- [ ] Code changes are complete and tested
- [ ] Documentation template is filled out
- [ ] Relevant documentation file is updated
- [ ] "Last Updated" date is set
- [ ] Code examples are included (if applicable)
- [ ] Related files are cross-referenced
- [ ] Documentation is reviewed along with code

---

## 🚀 Documentation Workflow

### Step 1: Make Your Code Changes

Write your code, test it, and ensure it works.

### Step 2: Choose the Right Template

Based on what you changed:

- **API Route** → Use API route template from `BACKEND_DOCUMENTATION_TEMPLATE.md`
- **Module/Agent** → Use module/agent template from `BACKEND_DOCUMENTATION_TEMPLATE.md`
- **Database Schema** → Use database change template
- **Bug Fix** → Use bug fix template
- **Feature** → Use feature addition template
- **Refactoring** → Use refactoring template

### Step 3: Fill Out the Template

Copy the relevant template from:

- **Backend**: `BACKEND_DOCUMENTATION_TEMPLATE.md` (in this folder)

Fill in all sections with:

- What changed
- Why it changed
- How it works
- Usage examples
- Any breaking changes

### Step 4: Update the Documentation File

Add your documentation to the appropriate file:

**Backend:**

- API changes → `BACKEND_API_ROUTES_DOCUMENTATION.md`
- Module changes → `BACKEND_MODULES_DOCUMENTATION.md`
- Architecture changes → `BACKEND_DOCUMENTATION.md`

### Step 5: Update "Last Updated" Date

At the bottom of the documentation file, update:

```markdown
**Last Updated**: [Current Date]
```

### Step 6: Commit Together

Commit documentation along with code changes:

```bash
git add .
git commit -m "feat: Add new feature

- Implemented new feature
- Updated documentation
- Added usage examples"
```

---

## 📝 Quick Reference

### What to Document

#### Always Document:

- ✅ New API endpoints
- ✅ New modules/agents
- ✅ Bug fixes
- ✅ New features
- ✅ Refactoring
- ✅ Performance optimizations
- ✅ Breaking changes
- ✅ Configuration changes
- ✅ Database schema changes

#### Don't Need Full Documentation:

- Minor typo fixes
- Formatting changes
- Comment-only changes

---

## 🎯 Examples

### Example 1: Adding a New API Route

1. **Code**: Create `backend/api/routes/new_feature.py`
2. **Template**: Use API route template from `BACKEND_DOCUMENTATION_TEMPLATE.md`
3. **Update**: Add to `BACKEND_API_ROUTES_DOCUMENTATION.md`
4. **Commit**: Include both code and documentation

### Example 2: Adding a New Module/Agent

1. **Code**: Create `backend/agents/new_agent.py`
2. **Template**: Use module/agent template from `BACKEND_DOCUMENTATION_TEMPLATE.md`
3. **Update**: Add to `BACKEND_MODULES_DOCUMENTATION.md`
4. **Commit**: Include both code and documentation

### Example 3: Fixing a Bug

1. **Code**: Fix the bug
2. **Template**: Use bug fix template
3. **Update**: Add to relevant documentation file
4. **Commit**: Include both fix and documentation

---

## ⚠️ Important Notes

### Documentation Quality Standards

1. **Be Specific**: Include file paths, function names, and code examples
2. **Explain Why**: Not just what changed, but why
3. **Include Examples**: Code examples help understanding
4. **Cross-Reference**: Link to related documentation
5. **Keep It Updated**: Update docs when code changes

### Common Mistakes to Avoid

- ❌ Forgetting to document changes
- ❌ Vague descriptions ("fixed bug")
- ❌ Missing code examples
- ❌ Not updating "Last Updated" date
- ❌ Documenting in wrong file
- ❌ Incomplete template sections

---

## 🔍 Finding the Right Template

### Backend Templates

Location: `BACKEND_DOCUMENTATION_TEMPLATE.md` (in this folder)

Templates available:

- API Route Change Template
- Module/Agent Change Template
- Database Change Template
- Bug Fix Template
- Feature Addition Template
- Refactoring Template
- Performance Optimization Template

---

## 📞 Need Help?

### Can't Find the Right Template?

- Check `BACKEND_DOCUMENTATION_TEMPLATE.md` for all available options
- Use the most similar template and adapt it
- Ask for help if unsure

### Not Sure What to Document?

- When in doubt, document it
- Better to over-document than under-document
- Review similar changes in existing documentation

### Documentation Review

- Code reviews should include documentation review
- Ensure documentation matches implementation
- Check for completeness and clarity

---

## ✅ Success Criteria

Good documentation should:

- ✅ Allow a new developer to understand the change
- ✅ Include code examples
- ✅ Explain the "why" not just the "what"
- ✅ Be easy to find and navigate
- ✅ Stay up-to-date with code

---

## 🎓 Remember

**Documentation is not optional - it's part of the code.**

Just like you wouldn't commit code without tests (when applicable), don't commit code without documentation.

---

**Last Updated**: 2025
