import re

test = "EXTERNAL EMAIL:  Don't click links or open attachments unless the content is expected and known to be safe."

patterns = [
    r"(?mi)^.*EXTERNAL\s+EMAIL\s*:.*(?:click|links?|attachments?|safe).*$",
    r"(?mi)^\s*external email[:\-].*$",
    r"(?mi)^.*expected\s+and\s+known\s+to\s+be\s+safe.*$",
]

print(f"Test string: {test!r}\n")

for i, p in enumerate(patterns):
    match = re.search(p, test)
    print(f"Pattern {i+1}: {'MATCH' if match else 'NO MATCH'}")
    if match:
        print(f"  Matched: {match.group()!r}")

# Now test the actual strip
cleaned = test
for p in patterns:
    cleaned = re.sub(p, "", cleaned)

print(f"\nAfter stripping: {cleaned!r}")
