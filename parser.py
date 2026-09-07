import ast
import os
import sys
from datetime import datetime, UTC
try:
    from db import get_session, Repo, Function, CallEdge, UnresolvedCall
except ImportError:
    from sementic_cb_search.db import get_session, Repo, Function, CallEdge, UnresolvedCall

class RepoASTVisitor(ast.NodeVisitor):
    def __init__(self):
        self.functions = []      # Flat list of dicts for all extracted functions
        self.classes = {}        # Class name -> list of base class names
        self.imports = {}        # Alias -> (original_name, module_path)
        self.class_stack = []    # Tracks active class names
        self.func_stack = []     # Tracks active function record dicts

    def visit_Import(self, node):
        for alias in node.names:
            alias_name = alias.asname or alias.name
            self.imports[alias_name] = (alias.name, alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        module = node.module or ""
        for alias in node.names:
            alias_name = alias.asname or alias.name
            self.imports[alias_name] = (alias.name, module)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(base.attr)
        self.classes[node.name] = bases
        
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node):
        self.process_function(node)

    def visit_AsyncFunctionDef(self, node):
        self.process_function(node)

    def process_function(self, node):
        if self.func_stack:
            kind = "nested"
        elif self.class_stack:
            kind = "method"
        else:
            kind = "function"

        class_name = self.class_stack[-1] if self.class_stack else None
        
        is_property = False
        for dec in getattr(node, "decorator_list", []):
            if isinstance(dec, ast.Name) and dec.id == "property":
                is_property = True
            elif isinstance(dec, ast.Attribute) and dec.attr == "property":
                is_property = True

        func_record = {
            "name": node.name,
            "class_name": class_name,
            "start_line": node.lineno,
            "end_line": getattr(node, "end_lineno", node.lineno),
            "kind": kind,
            "is_property": is_property,
            "calls": []  # List of tuples: (called_name, call_line)
        }

        self.func_stack.append(func_record)
        self.generic_visit(node)
        finished_func = self.func_stack.pop()
        self.functions.append(finished_func)

    def visit_Call(self, node):
        if hasattr(node, "func"):
            setattr(node.func, "_is_call_func", True)
        if self.func_stack:
            called_name = self.get_called_name(node.func)
            if called_name:
                self.func_stack[-1]["calls"].append((called_name, node.lineno))
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if self.func_stack and self.class_stack:
            if isinstance(node.value, ast.Name) and node.value.id == "self":
                if not getattr(node, "_is_call_func", False):
                    self.func_stack[-1]["calls"].append((node.attr, node.lineno))
        self.generic_visit(node)

    def get_called_name(self, node) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        elif isinstance(node, ast.Call):
            return self.get_called_name(node.func)
        return None

def parse_file_functions(file_path: str) -> dict:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            code_content = f.read()
        tree = ast.parse(code_content, filename=file_path)
        visitor = RepoASTVisitor()
        visitor.visit(tree)
        return {
            "functions": visitor.functions,
            "classes": visitor.classes,
            "imports": visitor.imports
        }
    except Exception as e:
        print(f"[WARNING] Failed to parse {file_path}: {e}")
        return {"functions": [], "classes": {}, "imports": {}}

def build_and_store_call_graph(metadata: dict) -> dict:
    repo_url = metadata["repo_url"]
    repo_name = metadata["repo_name"]
    source_files = metadata["source_files"]

    session = get_session()
    try:
        repo = session.query(Repo).filter(Repo.url == repo_url).first()
        if not repo:
            repo = Repo(
                name=repo_name,
                url=repo_url,
                clone_path=metadata["clone_path"],
                status="parsing",
                last_progress_at=datetime.now(UTC),
                ingested_at=datetime.now(UTC)
            )
            session.add(repo)
            session.commit()
            session.refresh(repo)
        else:
            repo.status = "parsing"
            repo.last_progress_at = datetime.now(UTC)
            repo.clone_path = metadata["clone_path"]
            session.query(Function).filter(Function.repo_id == repo.id).delete()
            session.commit()

        # 2. Parse files and collect metadata
        func_records = []
        file_imports_map = {}
        global_class_registry = {}  # class_name -> list of base class names

        for idx, sf in enumerate(source_files):
            file_path = sf["relative_path"]
            abs_path = sf["absolute_path"]
            parsed_data = parse_file_functions(abs_path)
            
            parsed_funcs = parsed_data["functions"]
            file_imports_map[file_path] = parsed_data["imports"]
            
            for cls_name, bases in parsed_data["classes"].items():
                global_class_registry.setdefault(cls_name, []).extend(bases)

            for pf in parsed_funcs:
                db_func = Function(
                    repo_id=repo.id,
                    file_path=file_path,
                    name=pf["name"],
                    class_name=pf["class_name"],
                    start_line=pf["start_line"],
                    end_line=pf["end_line"],
                    kind=pf["kind"]
                )
                session.add(db_func)
                func_records.append((db_func, pf["calls"]))

            # Periodic parser heartbeat touch every 20 files
            if (idx + 1) % 20 == 0 or (idx + 1) == len(source_files):
                r_heartbeat = session.query(Repo).filter(Repo.id == repo.id).first()
                if r_heartbeat:
                    r_heartbeat.last_progress_at = datetime.now(UTC)
                session.commit()

        session.commit()

        # 3. Build lookup structures
        all_funcs = session.query(Function).filter(Function.repo_id == repo.id).all()
        
        global_name_map = {}
        local_name_map = {}
        class_methods_map = {}  # (class_name, method_name) -> list of Functions

        for f in all_funcs:
            global_name_map.setdefault(f.name, []).append(f)
            local_name_map.setdefault((f.file_path, f.name), []).append(f)
            if f.class_name:
                class_methods_map.setdefault((f.class_name, f.name), []).append(f)

        # 4. Refined Call Resolution Algorithm
        resolved_count = 0
        unresolved_count = 0

        def resolve_inherited_method(class_name: str, method_name: str, visited=None):
            if visited is None:
                visited = set()
            if class_name in visited:
                return None
            visited.add(class_name)

            # Check direct method on this class
            candidates = class_methods_map.get((class_name, method_name), [])
            if candidates:
                return candidates[0]

            # Recurse up base classes
            bases = global_class_registry.get(class_name, [])
            for base in bases:
                res = resolve_inherited_method(base, method_name, visited)
                if res:
                    return res
            return None

        for db_func, calls in func_records:
            caller_id = db_func.id
            file_path = db_func.file_path
            caller_class = db_func.class_name

            for called_name, call_line in calls:
                resolved_callee = None

                # Tier A: Inheritance & Class Method Resolution (for methods in classes)
                if caller_class:
                    resolved_callee = resolve_inherited_method(caller_class, called_name)

                # Tier A2: Class Instantiation Resolution (e.g. Session() -> Session.__init__)
                if not resolved_callee:
                    init_candidates = class_methods_map.get((called_name, "__init__"), [])
                    if init_candidates:
                        resolved_callee = init_candidates[0]

                # Tier B: Same-File Local Resolution
                if not resolved_callee:
                    local_candidates = local_name_map.get((file_path, called_name), [])
                    if local_candidates:
                        nested = next((c for c in local_candidates if c.kind == "nested" and db_func.start_line <= c.start_line <= db_func.end_line), None)
                        resolved_callee = nested or local_candidates[0]

                # Tier C: Import Resolution
                if not resolved_callee and file_path in file_imports_map:
                    imports = file_imports_map[file_path]
                    if called_name in imports:
                        orig_symbol, module_path = imports[called_name]
                        mod_parts = module_path.split('.')
                        mod_name = mod_parts[-1] if mod_parts else ""

                        # Search global candidates matching original symbol & module path
                        candidates = global_name_map.get(orig_symbol, [])
                        for c in candidates:
                            if mod_name and (mod_name in c.file_path.replace('\\', '/').split('/')):
                                resolved_callee = c
                                break
                            elif not mod_name:
                                resolved_callee = c
                                break
                        if not resolved_callee and candidates:
                            resolved_callee = candidates[0]

                # Tier D: Global Fallback (Prioritize top-level functions over class methods)
                if not resolved_callee:
                    global_candidates = global_name_map.get(called_name, [])
                    if global_candidates:
                        # Prioritize top-level functions first
                        top_level = next((c for c in global_candidates if c.kind == "function"), None)
                        resolved_callee = top_level or global_candidates[0]

                # Record Result
                if resolved_callee:
                    edge = CallEdge(
                        caller_function_id=caller_id,
                        callee_function_id=resolved_callee.id,
                        call_line=call_line
                    )
                    session.add(edge)
                    resolved_count += 1
                else:
                    BUILTIN_AND_STDLIB_NAMES = {
                        "isinstance", "issubclass", "len", "str", "int", "float", "bool", "dict", "list",
                        "set", "tuple", "bytes", "type", "super", "getattr", "setattr", "hasattr", "delattr",
                        "range", "enumerate", "zip", "map", "filter", "any", "all", "min", "max", "sum",
                        "abs", "round", "divmod", "pow", "repr", "ascii", "ord", "chr", "bin", "oct", "hex",
                        "hash", "id", "open", "input", "print", "warn", "warning", "iter", "next", "callable",
                        "vars", "dir", "slice", "object", "classmethod", "staticmethod", "property", "cast",
                        "split", "rsplit", "splitlines", "strip", "lstrip", "rstrip", "lower", "upper",
                        "startswith", "endswith", "join", "replace", "find", "rfind", "index", "count",
                        "format", "encode", "decode", "append", "extend", "insert", "remove", "pop", "clear",
                        "copy", "update", "get", "keys", "values", "items", "setdefault", "read", "readline",
                        "readlines", "write", "writelines", "close", "seek", "tell", "flush",
                        "parametrize", "raises", "fixture", "mark", "xfail", "skip", "setenv", "monkeypatch",
                        "urlparse", "urlunparse", "urlsplit", "urlunsplit", "parse_qs", "parse_qsl", "quote",
                        "unquote", "quote_plus", "unquote_plus", "urllib3", "BytesIO", "StringIO", "Event", "Thread",
                        "ValueError", "TypeError", "KeyError", "AttributeError", "RuntimeError", "HTTPError",
                        "RequestException", "IOError", "OSError", "Exception", "StopIteration", "IndexError",
                        "headers", "data", "url", "method", "hooks", "cookies", "status_code", "username",
                        "password", "raw", "_store", "_content_consumed", "__dict__", "_thread_local", "frozenset",
                        "dumps", "loads", "socket", "sendall", "connect", "lookup_dict", "trust_env", "_r",
                        "case_insensitive_dict"
                    }
                    if called_name not in BUILTIN_AND_STDLIB_NAMES:
                        unresolved = UnresolvedCall(
                            caller_function_id=caller_id,
                            called_name=called_name,
                            call_line=call_line
                        )
                        session.add(unresolved)
                        unresolved_count += 1

        session.commit()

        return {
            "status": "success",
            "repo_id": repo.id,
            "functions_extracted": len(all_funcs),
            "call_edges_resolved": resolved_count,
            "unresolved_calls_recorded": unresolved_count
        }

    except Exception as e:
        session.rollback()
        r = session.query(Repo).filter(Repo.url == repo_url).first()
        if r:
            r.status = "failed"
            r.failed_stage = "parsing"
            r.failed_at = datetime.now(UTC)
            r.error_message = str(e)
            session.commit()
        raise e
    finally:
        session.close()
