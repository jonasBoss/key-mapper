import ast
import sys
import time
import traceback
from typing import Iterable, Set

from inputremapper.exceptions import MacroParsingError

safe_builtins = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "chr": chr,
    "complex": complex,
    "dict": dict,
    "divmod": divmod,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "hash": hash,
    "hex": hex,
    "int": int,
    "iter": iter,
    "len": len,
    "map": map,
    "max": max,
    "min": min,
    "next": next,
    "oct": oct,
    "ord": ord,
    "pow": pow,
    "property": property,
    "range": range,
    "repr": repr,
    "reversed": reversed,
    "round": round,
    "set": set,
    "slice": slice,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "type": type,
    "zip": zip,
}

shared_dict = {}


class FindSharedAndSanitize(ast.NodeVisitor):
    def __init__(self):
        self.shared_names = set()

    def __call__(self, node: ast.AST) -> Set[str]:
        self.shared_names.clear()
        self.visit(node)
        return self.shared_names.copy()

    def visit_Global(self, node: ast.Global):
        self.shared_names.update(node.names)

    def visit_Name(self, node: ast.Name):
        if node.id == "__shared_dict__":
            raise MacroParsingError(
                f"Error at {node.lineno}: "
                f"The '__shared_dict__' is sacred! DO NOT TOUCH!"
            )

    def visit_Import(self, node: ast.Import):
        raise MacroParsingError(f"Error at {node.lineno}: imports are not allowed")

    def visit_ImportFrom(self, node: ast.ImportFrom):
        raise MacroParsingError(f"Error at {node.lineno}: imports are not allowed")


class ParseMacroCode(ast.NodeTransformer):
    def __init__(self, global_vars: Iterable[str]):
        self.global_vars = global_vars
        super(ParseMacroCode, self).__init__()

    def visit_Global(self, node: ast.Global) -> None:
        """delete any
        >>> global var
        statements"""
        return None

    def visit_Name(self, node: ast.Name) -> ast.AST:
        """substitute any name access to a shared name
        with access to the shared_dict"""
        if node.id not in self.global_vars:
            return node

        if isinstance(node.ctx, ast.Load):
            new_node: ast.Call = ast.parse(
                f'__shared_dict__.get("{node.id}")', mode="eval"
            ).body
            new_node.ctx = node.ctx
            new_node.lineno = node.lineno
            new_node.end_lineno = node.end_lineno
            new_node.col_offset = node.col_offset
            return new_node
        elif isinstance(node.ctx, ast.Store) or isinstance(node.ctx, ast.Del):
            new_node: ast.Subscript = ast.parse(
                f'__shared_dict__["{node.id}"]', mode="eval"
            ).body
            new_node.ctx = node.ctx
            new_node.lineno = node.lineno
            new_node.end_lineno = node.end_lineno
            new_node.col_offset = node.col_offset
            return new_node
        raise AssertionError()


class Macro:
    def __init__(self, code: str):
        self.top_secret = "this is a secret"
        self.run = lambda: None
        self.raw_code = code

        tree = ast.parse(code)
        shared_names = FindSharedAndSanitize()(tree)
        ParseMacroCode(shared_names).visit(tree)

        print(ast.unparse(tree))

        bytecode = compile(tree, "User Macro", "exec", ast.PyCF_TYPE_COMMENTS)
        scope = {
            "__builtins__": safe_builtins,
            "__shared_dict__": shared_dict,
            "do_something": self.do_something,
            "sleep": self.sleep,
        }
        exec(bytecode, scope)
        self.run = scope["run"]

    def do_something(self, whatever):
        print(whatever)

    def sleep(self, t: float):
        time.sleep(t)


if __name__ == "__main__":
    code = """
#comment
#import typing

#class Baz:
#    my_var = 20
    
global my_var
global another_var
another_var = 1
local_var = my_var
d = {}
d["foo"] = 10
g = d["foo"]
h = d.get("bar")
def do_something_unsafe():
    print("hallo welt!")
    
def run():
    for i in range(local_var):
        #from os import foo
        do_something(str(i))
        sleep(1)
        global foo
        foo = 1
    
    #do_something_unsafe()
"""
    m = Macro(code)
    try:
        m.run()
    except Exception:
        exc_type, exc, tb = sys.exc_info()
        msg = "".join(traceback.format_tb(tb))
        tb = traceback.extract_tb(tb)
        msg += m.raw_code.splitlines()[tb[-1].lineno - 1]
        print(msg)
        print(exc)
