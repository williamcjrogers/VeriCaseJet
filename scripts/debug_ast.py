import ast

code = """
from .admin_approval import (
    router as admin_approval_router,
)
from .correspondence.routes import (
    router as correspondence_router,
)
from .enhanced_api_routes import (
    aws_router,
)
"""

router_imports = {}

tree = ast.parse(code)
for node in ast.walk(tree):
    if isinstance(node, ast.ImportFrom) and node.module:
        mod_name = ("." * node.level) + node.module if node.level > 0 else node.module
        print(
            f"Found import: module={node.module}, level={node.level}, mod_name={mod_name}"
        )
        for name in node.names:
            print(f"  - name={name.name}, asname={name.asname}")
            # Track all imports. If asname exists, use it, otherwise use name.
            imported_as = name.asname if name.asname else name.name
            router_imports[imported_as] = mod_name

print("Router Imports:", router_imports)
