# Welbourne Refine Skill

**Version**: 1.0  
**Created**: 12 December 2025  
**Project**: Welbourne Tottenham Hale (WR200625/02809)

## Purpose
Specialized workflow combining spam classification with bulk deletion capabilities for cleaning the Welbourne PST email database (55,981 emails post-cleaning).

## Files in This Skill

### SKILL.md
Main skill definition containing:
- When to use this skill
- Spam pattern detection categories (HIGH/MEDIUM confidence)
- Bulk deletion workflow patterns
- Welbourne-specific context and protected keywords
- Safety protocols and confirmation requirements
- Example interactions and advanced techniques
- Integration with VeriCase metadata system

### spam_filter.py
Python classifier implementation:
- Pattern-based email classification
- Confidence scoring (0-100)
- Category identification
- Auto-hide flagging for correspondence views
- Batch classification support

### QUICK_REFERENCE.md
Operational quick reference:
- One-liner search commands
- PowerShell bulk deletion scripts
- Safety check procedures
- Common pattern cheat sheet
- Database impact tracking formulas

## Key Features

### Pattern Detection
- **HIGH CONFIDENCE** (auto-delete candidates): Marketing, LinkedIn, news digests, date-only subjects, vendor spam
- **MEDIUM CONFIDENCE** (review required): Out-of-office, HR automated, surveys, training, leave requests
- **Sender patterns**: noreply@, marketing@, LinkedIn notifications, event platforms

### Safety Protocols
✓ Always show 5-10 samples before bulk deletion  
✓ Explicit confirmation required for all deletions  
✓ Cross-reference against protected keywords  
✓ Preserve critical senders (e.g., noreply@aconex.com)  
✓ Backup recommendations for large deletions (500+)  
✓ Detailed deletion reporting with database impact

### Protected Content
Never delete emails containing:
- Claim keywords: vobster, s278, s106, remedial, defects, variation
- Subcontractors: ljj, grangewood, keylon, weldrite, taylor maxwell
- Design team: tps, calfordseaden, pte, czwg, argent
- Commercial terms: claim, payment, valuation, loss and expense
- Programme terms: delay, completion, critical path, handover

## Usage Examples

### Basic Marketing Cleanup
```
William: "Use Welbourne Refine to clean up marketing emails"
→ Claude searches, shows samples, gets confirmation, deletes, reports impact
```

### LinkedIn Purge
```
William: "Remove LinkedIn notifications"
→ Claude finds LinkedIn patterns, shows examples, confirms deletion
```

### Protected Content Detection
```
William: "Delete all noreply emails"
→ Claude detects noreply@aconex.com (839 emails - CRITICAL)
→ Recommends keeping Aconex, deleting only other noreply@ senders
```

## Integration with Desktop Commander

Uses Desktop Commander's capabilities:
- `start_search` for pattern-based email discovery
- `get_more_search_results` for progressive result retrieval
- PowerShell `Remove-Item` for batch file deletion
- `read_file` for content verification
- Search with `literalSearch=false` for regex patterns

## Database Context

**Current State**:
- Database size: 55,981 emails (post-initial cleaning)
- Target reduction: 5-10% (2,799-5,598 low-value emails)
- Quality goal: Correspondence view shows only actionable emails

**Top Contributors** (preserved):
- Jamie Albone (21,213 emails)
- Robert Palmer (11,595 emails)
- John Angell@LJJ (4,733 emails)
- Darren Hancock@LJJ (3,512 emails)

**Email Domains**:
- 50 external domains identified
- Critical: ljjcontractors.co.uk, czwgarchitects.co.uk, calfordseaden.com
- Project management: aconex.com (MUST PRESERVE)

## Success Metrics

Track effectiveness:
- Noise reduction: Target 5-10% database size reduction
- Content preservation: 100% of claim-relevant emails retained
- View quality: Correspondence view contains only actionable content
- Audit compliance: Complete deletion log maintained

## Version History

- **v1.0** (12 Dec 2025): Initial release combining spam_filter.py with bulk deletion workflow

## Support

For questions or issues with this skill:
1. Review SKILL.md for detailed patterns and workflows
2. Check QUICK_REFERENCE.md for operational commands
3. Refer to spam_filter.py for classification logic
4. Test with small batches before large-scale deletions

---

**Status**: ✅ Ready for use  
**Testing**: Recommended to start with HIGH confidence patterns on small batch (50-100 emails)
