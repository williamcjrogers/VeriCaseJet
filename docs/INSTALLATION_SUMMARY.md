# Welbourne Refine Skill - Installation Complete ✅

**Created**: 12 December 2025  
**Location**: `C:\Users\William\.claude\mcp-user-skills\welbourne-refine`  
**Status**: Ready for use

## What Was Created

### 5 Files in Skill Directory

1. **SKILL.md** (358 lines)
   - Main skill definition with complete workflow patterns
   - High/Medium confidence spam categories
   - Welbourne-specific context and protected keywords
   - Safety protocols and confirmation requirements
   - 8 detailed implementation patterns
   - Integration with VeriCase metadata system

2. **spam_filter.py** (324 lines)
   - Python-based email classifier
   - Pattern matching with regex support
   - Confidence scoring (0-100)
   - Batch classification capability
   - Singleton pattern for efficiency

3. **QUICK_REFERENCE.md** (216 lines)
   - One-liner search commands
   - PowerShell bulk deletion scripts
   - Safety check procedures
   - Pattern cheat sheet table
   - Database impact tracking formulas

4. **README.md** (133 lines)
   - Skill overview and purpose
   - File structure documentation
   - Usage examples
   - Integration notes
   - Success metrics and version history

5. **example_deletion.ps1** (287 lines)
   - Complete PowerShell deletion workflow
   - Pattern-based search by category
   - Protected content verification
   - Backup functionality
   - Dry-run mode for testing
   - Detailed progress reporting

**Total Lines**: 1,318 lines of documentation and code

## Key Capabilities

### Spam Detection Categories

**HIGH CONFIDENCE (auto-delete candidates):**
- Marketing: webinars, exhibitions, conferences, discounts
- LinkedIn: profile views, connection notifications  
- News digests: contractor appointments, industry news
- Date-only subjects: timestamp-only emails
- Vendor spam: Toolstation, Screwfix promotions

**MEDIUM CONFIDENCE (review required):**
- Out-of-office replies
- HR automated messages
- Surveys and feedback requests
- Training/CPD notifications
- Leave request confirmations

### Safety Features

✓ **Always show samples** before deletion (5-10 examples minimum)  
✓ **Explicit confirmation** required for all bulk operations  
✓ **Protected keyword check** against claim-related terms  
✓ **Protected sender preservation** (e.g., noreply@aconex.com)  
✓ **Backup recommendations** for large deletions (500+)  
✓ **Detailed reporting** with database impact percentages

### Protected Content

Never deletes emails containing:
- **Claim keywords**: vobster, s278, s106, remedial, defects, variation
- **Subcontractors**: ljj, grangewood, keylon, weldrite, taylor maxwell
- **Design team**: tps, calfordseaden, pte, czwg, argent
- **Commercial**: claim, payment, valuation, loss and expense
- **Programme**: delay, completion, critical path, handover

## How to Use

### Quick Start
```
William: "Use Welbourne Refine to clean up marketing emails"
→ Claude searches database, shows samples, gets confirmation, deletes, reports impact
```

### Step-by-Step Process
1. **Search**: Claude uses Desktop Commander to find spam patterns
2. **Review**: Shows 5-10 example emails with spam indicators
3. **Confirm**: Gets explicit "yes/DELETE" confirmation from you
4. **Delete**: Executes PowerShell bulk deletion
5. **Report**: "Deleted X emails (Y% of database), remaining: Z emails"

### Example Commands

**Marketing cleanup**:
```
"Clean up marketing emails from Welbourne"
"Remove webinar and conference spam"
```

**LinkedIn purge**:
```
"Delete LinkedIn notifications"
"Remove profile view emails"
```

**Date-only subjects**:
```
"Clean up emails with date-only subjects"
"Delete timestamp-only emails"
```

**Sender-based**:
```
"Remove noreply emails (but keep Aconex)"
"Delete all eventbrite notifications"
```

## Integration with Your Systems

### Desktop Commander
- Uses `start_search` for pattern discovery
- Uses `get_more_search_results` for progressive retrieval
- PowerShell `Remove-Item` for batch deletion
- Regex pattern matching with `literalSearch=false`

### VeriCase Integration
Can tag emails in metadata instead of immediate deletion:
```json
{
  "spam_classification": {
    "is_spam": true,
    "score": 95,
    "category": "marketing",
    "is_hidden": true,
    "classified_date": "2025-12-12"
  }
}
```

### Bulk Delete Capability
Leverages your existing bulk deletion workflow:
- Search → Confirm → Delete pattern
- PowerShell batch operations
- Error handling and retry logic
- Audit trail maintenance

## Welbourne Database Context

**Current State**:
- Total emails: 55,981 (post-cleaning)
- Target reduction: 5-10% (2,799-5,598 low-value emails)
- Quality goal: Show only actionable correspondence

**Key People** (preserved):
- Jamie Albone (21,213 emails)
- Robert Palmer (11,595 emails)  
- John Angell@LJJ (4,733 emails)
- Darren Hancock@LJJ (3,512 emails)

**Critical Domains**:
- ljjcontractors.co.uk (main contractor)
- czwgarchitects.co.uk (architect)
- calfordseaden.com (engineer)
- aconex.com (project management - MUST PRESERVE)

## Testing Recommendations

### Start Small
1. Test with date-only subjects (low risk, easy to identify)
2. Expected: ~150-200 emails, 0.3% reduction
3. Verify: No protected content in results

### Progress to Medium
2. Marketing emails (high confidence)
3. Expected: ~250-300 emails, 0.5% reduction
4. Review: Check for conference/webinar false positives

### Review Before Scaling
3. LinkedIn notifications (very high confidence)
4. Expected: ~100-150 emails, 0.2% reduction
5. Safe: LinkedIn emails rarely contain project info

### Total Expected Cleanup
- Conservative: 500-1,000 emails (0.9-1.8%)
- Moderate: 1,500-2,500 emails (2.7-4.5%)
- Aggressive: 3,000-5,000 emails (5.4-8.9%)

## Success Criteria

✓ **No false positives**: Zero claim-related emails deleted  
✓ **Noise reduction**: 5-10% database size reduction achieved  
✓ **View quality**: Correspondence shows only actionable emails  
✓ **Audit compliance**: Complete deletion log maintained  
✓ **Time savings**: Faster email review and analysis

## Next Steps

1. **Review the SKILL.md** for complete workflow patterns
2. **Check QUICK_REFERENCE.md** for operational commands  
3. **Test with small batch** (50-100 emails) using dry-run mode
4. **Scale progressively** based on confidence and results
5. **Document outcomes** for VeriCase integration planning

## Support Resources

- **SKILL.md**: Detailed patterns and workflows (358 lines)
- **QUICK_REFERENCE.md**: Operational commands (216 lines)
- **spam_filter.py**: Classification logic (324 lines)
- **example_deletion.ps1**: Complete workflow script (287 lines)
- **README.md**: Overview and examples (133 lines)

## Version Information

- **Skill Version**: 1.0
- **Python Classifier**: Pattern-based with confidence scoring
- **PowerShell Scripts**: Windows-optimized batch operations
- **Safety Level**: High (multiple confirmation layers)
- **Testing Status**: Ready for initial pilot testing

---

## Installation Verification ✓

Location: `C:\Users\William\.claude\mcp-user-skills\welbourne-refine`

Files created:
- [✓] SKILL.md (358 lines)
- [✓] spam_filter.py (324 lines)
- [✓] QUICK_REFERENCE.md (216 lines)
- [✓] README.md (133 lines)
- [✓] example_deletion.ps1 (287 lines)

**Status**: Installation complete and ready for use

**Skill will be available** in Claude upon next restart or skill directory refresh.

---

*Welbourne Refine combines your spam filter analysis with bulk deletion capabilities to efficiently clean construction project email databases while protecting critical claim-related correspondence.*
