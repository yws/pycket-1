#! /usr/bin/env python
# -*- coding: utf-8 -*-
#
import os
import sys

from rpython.rlib import streamio
from rpython.rlib.rbigint import rbigint
from rpython.rlib.objectmodel import specialize, we_are_translated
from rpython.rlib.rstring import ParseStringError, ParseStringOverflowError
from rpython.rlib.rarithmetic import string_to_int
from pycket import pycket_json
from pycket.error import SchemeException
from pycket.interpreter import *
from pycket import values, values_string
from pycket import values_regex
from pycket import vector
from pycket import values_struct
from pycket.hash.simple import W_EqualImmutableHashTable, make_simple_immutable_table

class ExpandException(SchemeException):
    pass

class PermException(SchemeException):
    pass

#### ========================== Utility functions

def readfile(fname):
    "NON_RPYTHON"
    f = open(fname)
    s = f.read()
    f.close()
    return s

def readfile_rpython(fname):
    f = streamio.open_file_as_stream(fname)
    s = f.readall()
    f.close()
    return s


#### ========================== Functions for expanding code to json

fn = "-l pycket/expand --"
be = "-l pycket/zo-expand --"


current_racket_proc = None

def expand_string(s, reuse=True, srcloc=True, byte_option=False, tmp_file_name=False):
    "NON_RPYTHON"
    global current_racket_proc
    from subprocess import Popen, PIPE

    if not byte_option:
        cmd = "racket %s --loop --stdin --stdout %s" % (fn, "" if srcloc else "--omit-srcloc")
    else:
        tmp_module = tmp_file_name + '.rkt'
        cmd = "racket -l pycket/zo-expand -- --stdout %s" % tmp_module

    if current_racket_proc and reuse and current_racket_proc.poll() is None:
        process = current_racket_proc
    else:
        process = Popen(cmd, shell=True, stdin=PIPE, stdout=PIPE)
        if reuse:
            current_racket_proc = process
    if reuse:
        if not byte_option:
            process.stdin.write(s.encode("utf-8"))
            ## I would like to write something so that Racket sees EOF without
            ## closing the file. But I can't figure out how to do that. It
            ## must be possible, though, because bash manages it.
            #process.stdin.write(chr(4))
            process.stdin.write("\n\0\n")
            process.stdin.flush()
            #import pdb; pdb.set_trace()
        data = process.stdout.readline()
    else:
        (data, err) = process.communicate(s)
    if len(data) == 0:
        raise ExpandException("Racket did not produce output. Probably racket is not installed, or it could not parse the input.")
    # if err:
    #     raise ExpandException("Racket produced an error")
    return data

def expand_file(fname):
    "NON_RPYTHON"
    from subprocess import Popen, PIPE

    cmd = "racket %s --stdout \"%s\"" % (fn, fname)
    process = Popen(cmd, shell=True, stdin=PIPE, stdout=PIPE)
    data, err = process.communicate()
    if len(data) == 0:
        raise ExpandException("Racket did not produce output. Probably racket is not installed, or it could not parse the input.")
    if err:
        raise ExpandException("Racket produced an error")
    return data

# Call the Racket expander and read its output from STDOUT rather than producing an
# intermediate (possibly cached) file.
def expand_file_rpython(rkt_file, lib=fn):
    from rpython.rlib.rfile import create_popen_file
    cmd = "racket %s --stdout \"%s\" 2>&1" % (lib, rkt_file)
    if not os.access(rkt_file, os.R_OK):
        raise ValueError("Cannot access file %s" % rkt_file)
    pipe = create_popen_file(cmd, "r")
    out = pipe.read()
    err = os.WEXITSTATUS(pipe.close())
    if err != 0:
        raise ExpandException("Racket produced an error and said '%s'" % out)
    return out

def expand_file_cached(rkt_file, modtable, lib=fn):
    dbgprint("expand_file_cached", "", lib=lib, filename=rkt_file)

    try:
        json_file = ensure_json_ast_run(rkt_file, lib)
    except PermException:
        return expand_to_ast(rkt_file, modtable, lib)
    return load_json_ast_rpython(json_file, modtable, lib)

# Expand and load the module without generating intermediate JSON files.
def expand_to_ast(fname, modtable, lib=fn, byte_flag=False):
    if byte_flag:
        lib = be
    data = expand_file_rpython(fname, lib)
    reader = JsonReader(modtable, lib)
    return reader.to_module(pycket_json.loads(data)).assign_convert_module()

def expand(s, wrap=False, stdlib=False):
    data = expand_string(s)
    return pycket_json.loads(data)

def wrap_for_tempfile(func):
    def wrap(rkt_file, json_file, lib=fn):
        "NOT_RPYTHON"
        try:
            os.remove(json_file)
        except IOError:
            pass
        except OSError:
            pass
        from tempfile import mktemp
        json_file = os.path.realpath(json_file)
        tmp_json_file = mktemp(suffix='.json',
                               prefix=json_file[:json_file.rfind('.')])
        out = func(rkt_file, tmp_json_file, lib) # this may be a problem in the future if the given func doesn't expect a third arg (lib)
        assert tmp_json_file == out
        os.rename(tmp_json_file, json_file)
        return json_file

    wrap.__name__ = func.__name__
    return wrap

def expand_file_to_json(rkt_file, json_file, lib=fn):
    if not we_are_translated():
        return wrap_for_tempfile(_expand_file_to_json)(rkt_file, json_file, lib)
    return _expand_file_to_json(rkt_file, json_file, lib)

def _expand_file_to_json(rkt_file, json_file, lib=fn, byte_flag=False):
    lib = be if byte_flag else fn

    dbgprint("_expand_file_to_json", "", lib=lib, filename=rkt_file)

    from rpython.rlib.rfile import create_popen_file
    if not os.access(rkt_file, os.R_OK):
        raise ValueError("Cannot access file %s" % rkt_file)
    if not os.access(rkt_file, os.W_OK):
        # we guess that this means no permission to write the json file
        raise PermException(rkt_file)
    try:
        os.remove(json_file)
    except IOError:
        pass
    except OSError:
        pass
    # print "Expanding %s to %s" % (rkt_file, json_file)
    cmd = "racket %s --output \"%s\" \"%s\" 2>&1" % (
        fn,
        json_file, rkt_file)

    if "zo-expand" in lib:
        print "Transforming %s bytecode to %s" % (rkt_file, json_file)
        cmd = "racket %s %s" % (lib, rkt_file)
    else:
        print "Expanding %s to %s" % (rkt_file, json_file)

    # print cmd
    pipe = create_popen_file(cmd, "r")
    out = pipe.read()
    err = os.WEXITSTATUS(pipe.close())
    if err != 0:
        raise ExpandException("Racket produced an error and said '%s'" % out)
    return json_file

def expand_code_to_json(code, json_file, stdlib=True, mcons=False, wrap=True):
    from rpython.rlib.rfile import create_popen_file
    try:
        os.remove(json_file)
    except IOError:
        pass
    except OSError:
        pass
    cmd = "racket %s --output \"%s\" --stdin" % (
        fn,
        json_file)
    # print cmd
    pipe = create_popen_file(cmd, "w")
    pipe.write("#lang s-exp pycket%s" % (" #:stdlib" if stdlib else ""))
    pipe.write(code)
    err = os.WEXITSTATUS(pipe.close())
    if err != 0:
        raise ExpandException("Racket produced an error we failed to record")
    return json_file


def needs_update(file_name, json_name):
    try:
        file_mtime = os.stat(file_name).st_mtime
        if os.access(json_name, os.F_OK):
            if file_mtime < os.stat(json_name).st_mtime:
                return False
    except OSError:
        pass
    return True


def _json_name(file_name, lib=fn):
    if 'zo-expand' in lib:
        fileDirs = file_name.split("/")
        l = len(fileDirs)
        k = l-1 # is there a better way to do this (prove that the slice below has a non-negative stop)
        assert k >= 0
        modName = fileDirs[k]
        subs = fileDirs[0:k]
        subsStr = '/'.join(subs)
        if len(subs) > 0:
            subsStr += '/'
        return subsStr + 'fromBytecode_' + modName + '.json'
    else:
        return file_name + '.json'

def ensure_json_ast_run(file_name, lib=fn):
    json = _json_name(file_name, lib)

    dbgprint("ensure_json_ast_run", json, lib=lib, filename=file_name)

    if needs_update(file_name, json):
        return expand_file_to_json(file_name, json, lib)
    else:
        return json

def ensure_json_ast_eval(code, file_name, stdlib=True, mcons=False, wrap=True):
    json = _json_name(file_name)
    if needs_update(file_name, json):
        return expand_code_to_json(code, json, stdlib, mcons, wrap)
    else:
        return json


#### ========================== Functions for parsing json to an AST

def load_json_ast_rpython(fname, modtable, lib=fn, byte_flag=False):
    dbgprint("load_json_ast_rpython", "", lib=lib, filename=fname)
    if byte_flag:
        lib = be
    data = readfile_rpython(fname)
    reader = JsonReader(modtable, lib)
    return reader.to_module(pycket_json.loads(data)).assign_convert_module()

def parse_ast(json_string):
    json = pycket_json.loads(json_string)
    modtable = ModTable()
    return to_ast(json, modtable)

def parse_module(json_string, lib=fn):
    json = pycket_json.loads(json_string)
    modtable = ModTable()
    reader = JsonReader(modtable, fn)
    return reader.to_module(json).assign_convert_module()

def to_ast(json, modtable, lib=fn):
    reader = JsonReader(modtable, fn)
    ast = reader.to_ast(json)
    return ast.assign_convert(variable_set(), None)

#### ========================== Implementation functions

DO_DEBUG_PRINTS = False

@specialize.argtype(1)
def dbgprint(funcname, json, lib="", filename=""):
    # This helped debugging segfaults
    if DO_DEBUG_PRINTS:
        if isinstance(json, pycket_json.JsonBase):
            s = json.tostring()
        else:
            # a list
            s = "[" + ", ".join([j.tostring() for j in json]) + "]"
        print "Entering %s with: json - %s | lib - %s | filename - %s " % (funcname, s, lib, filename)

def to_formals(json):
    dbgprint("to_formals", json)
    make = values.W_Symbol.make
    lex  = lambda x : x.value_object()["lexical"].value_string()
    if json.is_object:
        obj = json.value_object()
        if "improper" in obj:
            improper_arr = obj["improper"]
            regular, last = improper_arr.value_array()
            regular_symbols = [make(lex(x)) for x in regular.value_array()]
            last_symbol = make(lex(last))
            return regular_symbols, last_symbol
        elif "lexical" in obj:
            return [], make(obj["lexical"].value_string())
    elif json.is_array:
        arr = json.value_array()
        return [make(lex(x)) for x in arr], None
    assert 0

def mksym(json):
    dbgprint("mksym", json)
    j = json.value_object()
    for i in ["toplevel", "lexical", "module"]:
        if i in j:
            return values.W_Symbol.make(j[i].value_string())
    assert 0, json.tostring()

# A table listing all the module files that have been loaded.
# A module need only be loaded once.
# Modules (aside from builtins like #%kernel) are listed in the table
# as paths to their implementing files which are assumed to be normalized.
class ModTable(object):
    _immutable_fields_ = ["table"]

    def __init__(self):
        self.table = {}
        self.current_modules = []

    def add_module(self, fname, module):
        self.table[fname] = module

    def push(self, fname):
        self.current_modules.append(fname)

    def pop(self):
        if not self.current_modules:
            raise SchemeException("No current module")
        self.current_modules.pop()

    def current_mod(self):
        if not self.current_modules:
            return None
        return self.current_modules[-1]

    @staticmethod
    def builtin(fname):
        return fname.startswith("#%")

    def has_module(self, fname):
        return ModTable.builtin(fname) or fname in self.table

    def lookup(self, fname):
        if fname.startswith("#%"):
            return None
        return self.table[fname]

    def enter_module(self, fname):
        # Pre-emptive pushing to prevent recursive expansion due to submodules
        # which reference the enclosing module
        self.push(fname)
        self.add_module(fname, None)

    def exit_module(self, fname, module):
        self.add_module(fname, module)
        self.pop()

def shorten_submodule_path(path):
    if path is None:
        return None
    acc = []
    for p in path:
        if p == ".":
            continue
        if p == "..":
            assert acc, "Malformed submodule path"
            acc.pop()
        else:
            acc.append(p)
    return acc[:]

def get_srcloc(o):
    pos = o["position"].value_int() if "position" in o else -1
    source = o["source"] if "source" in o else None
    if source and source.is_object:
        v = source.value_object()
        if "%p" in v:
            sourcefile = v["%p"].value_string()
        elif "quote" in v:
            sourcefile = v["quote"].value_string()
        else:
            assert 0
    else:
        sourcefile = None
    return (pos, sourcefile)

def convert_path(path):
    return [p.value_string() for p in path]

def parse_path(p):
    assert len(p) >= 1
    arr = convert_path(p)
    srcmod, path = arr[0], arr[1:]
    # Relative module names go into the path.
    # None value for the srcmod indicate the current module
    if srcmod in [".", ".."]:
        path   = arr
        srcmod = None
    return srcmod, path

class JsonReader(object):

    def __init__(self, modtable, lib):
        self.modtable = modtable
        self.lib = lib

    def to_bindings(self, arr):
        #dbgprint("to_bindings", arr)
        varss = [None] * len(arr)
        rhss  = [None] * len(arr)
        for i, v in enumerate(arr):
            varr = v.value_array()
            fmls = [values.W_Symbol.make(x.value_string()) for x in varr[0].value_array()]
            rhs = self.to_ast(varr[1])
            varss[i] = fmls
            rhss[i]  = rhs
        return varss, rhss

    def _to_lambda(self, lam):
        fmls, rest = to_formals(lam["lambda"])
        pos, sourcefile = get_srcloc(lam)
        body = [self.to_ast(x) for x in lam["body"].value_array()]
        return make_lambda(fmls, rest, body, pos, sourcefile)

    def _to_require(self, fname, path=None, lib=fn):
        dbgprint("_to_require", fname, lib=self.lib, filename=fname)
        path = shorten_submodule_path(path)
        modtable = self.modtable

        if modtable.has_module(fname):
            if modtable.builtin(fname):
                return VOID
            return Require(fname, modtable, path=path)
        modtable.enter_module(fname)
        module = expand_file_cached(fname, modtable, lib)
        modtable.exit_module(fname, module)
        return Require(fname, modtable, path=path)

    def _parse_require(self, path):
        dbgprint("parse_require", path, self.lib, path)
        fname, subs = path[0], path[1:]
        if fname in [".", ".."]:
            # fname field is not used in this case, so we just give an idea of which
            # module we are in
            return Require(self.modtable.current_mod(), None, path=path)
        return self._to_require(fname, path=subs)

    def to_module(self, json):
        dbgprint("to_module", json, lib=self.lib, filename="")

        # YYY
        obj = json.value_object()
        assert "body-forms" in obj, "got malformed JSON from expander"

        config = {}
        try:
            config_obj = obj["config"].value_object()
        except KeyError:
            pass
        else:
            for k, v in config_obj.iteritems():
                config[k] = v.value_string()

        try:
            lang_arr = obj["language"].value_array()
        except KeyError:
            lang = None
        else:
            lang = self._parse_require([lang_arr[0].value_string()]) if lang_arr else None

        body = [self.to_ast(x) for x in obj["body-forms"].value_array()]
        name = obj["module-name"].value_string()
        return Module(name, body, config, lang=lang)

    @staticmethod
    def is_builtin_operation(rator):
        return ("source-name" in rator and
                    ("source-module" not in rator or
                    rator["source-module"].value_string() == "#%kernel"))

    def to_ast(self, json):
        dbgprint("to_ast", json, lib=self.lib, filename="")
        mksym = values.W_Symbol.make

        if json.is_array:
            arr = json.value_array()
            rator = arr[0].value_object()
            if JsonReader.is_builtin_operation(rator):
                ast_elem = rator["source-name"].value_string()
                if ast_elem == "begin":
                    return Begin([self.to_ast(x) for x in arr[1:]])
                if ast_elem == "#%expression":
                    return self.to_ast(arr[1])
                if ast_elem == "set!":
                    target = arr[1].value_object()
                    var = None
                    if "source-name" in target:
                        srcname = mksym(target["source-name"].value_string())
                        if "source-module" in target:
                            if target["source-module"].is_array:
                                path_arr = target["source-module"].value_array()
                                srcmod, path = parse_path(path_arr)
                            else:
                                srcmod = path = None
                        else:
                            srcmod = "#%kernel"
                            path   = None

                        modname = mksym(target["module"].value_string()) if "module" in target else srcname
                        var = ModuleVar(modname, srcmod, srcname, path)
                    elif "lexical" in target:
                        var = CellRef(values.W_Symbol.make(target["lexical"].value_string()))
                    elif "toplevel" in target:
                        var = ToplevelVar(mksym(target["toplevel"].value_string()))
                    return SetBang(var, self.to_ast(arr[2]))
                if ast_elem == "#%top":
                    assert 0
                    return CellRef(mksym(arr[1].value_object()["symbol"].value_string()))
                if ast_elem == "begin-for-syntax":
                    return VOID
                if ast_elem == "define-syntaxes":
                    return VOID
                # The parser now ignores `#%require` AST nodes.
                # The actual file to include is now generated by expander
                # as an object that is handled below.
                if ast_elem == "#%require":
                    return VOID
                if ast_elem == "#%provide":
                    return VOID
            assert 0, "Unexpected ast-element element: %s" % json.tostring()
        if json.is_object:
            obj = json.value_object()
            if "require" in obj:
                paths = obj["require"].value_array()
                requires = []
                for path in paths:
                    path = convert_path(path.value_array())
                    if not path:
                        continue
                    requires.append(self._parse_require(path))
                return Begin.make(requires) if requires else VOID
            if "begin0" in obj:
                fst = self.to_ast(obj["begin0"])
                rst = [self.to_ast(x) for x in obj["begin0-rest"].value_array()]
                if len(rst) == 0:
                    return fst
                else:
                    return Begin0.make(fst, rst)
            if "begin-for-syntax" in obj:
                body = [self.to_ast(x) for x in obj["begin-for-syntax"].value_array()]
                return BeginForSyntax(body)
            if "wcm-key" in obj:
                return WithContinuationMark(self.to_ast(obj["wcm-key"]),
                                            self.to_ast(obj["wcm-val"]),
                                            self.to_ast(obj["wcm-body"]))
            if "define-values" in obj:
                binders = obj["define-values"].value_array()
                display_names = obj["define-values-names"].value_array()
                fmls = [mksym(x.value_string()) for x in binders]
                disp_syms = [mksym(x.value_string()) for x in display_names]
                body = self.to_ast(obj["define-values-body"])
                return DefineValues(fmls, body, disp_syms)
            if "letrec-bindings" in obj:
                body = [self.to_ast(x) for x in obj["letrec-body"].value_array()]
                bindings = obj["letrec-bindings"].value_array()
                if len(bindings) == 0:
                    return Begin.make(body)
                else:
                    vs, rhss = self.to_bindings(bindings)
                    assert isinstance(rhss[0], AST)
                    return make_letrec(list(vs), list(rhss), body)
            if "let-bindings" in obj:
                body = [self.to_ast(x) for x in obj["let-body"].value_array()]
                bindings = obj["let-bindings"].value_array()
                if len(bindings) == 0:
                    return Begin.make(body)
                else:
                    vs, rhss = self.to_bindings(bindings)
                    assert isinstance(rhss[0], AST)
                    return make_let(list(vs), list(rhss), body)
            if "variable-reference" in obj:
                current_mod = self.modtable.current_mod()
                if obj["variable-reference"].is_bool: # assumes that only boolean here is #f
                    return VariableReference(None, current_mod)
                else:
                    var = self.to_ast(obj["variable-reference"])
                    return VariableReference(var, current_mod)
            if "lambda" in obj:
                    return CaseLambda([self._to_lambda(obj)])
            if "case-lambda" in obj:
                    lams = [self._to_lambda(v.value_object()) for v in obj["case-lambda"].value_array()]
                    return CaseLambda(lams)
            if "operator" in obj:
                rator = self.to_ast(obj["operator"])
                rands = [self.to_ast(x) for x in obj["operands"].value_array()]
                return App.make_let_converted(rator, rands)
            if "test" in obj:
                cond = self.to_ast(obj["test"])
                then = self.to_ast(obj["then"])
                els  = self.to_ast(obj["else"])
                return If.make_let_converted(cond, then, els)
            if "quote" in obj:
                return Quote(to_value(obj["quote"]))
            if "quote-syntax" in obj:
                return QuoteSyntax(to_value(obj["quote-syntax"]))
            if "source-name" in obj:
                srcname = obj["source-name"].value_string()
                modname = obj["module"].value_string() if "module" in obj else None
                srcsym = mksym(srcname)
                modsym = mksym(modname) if modname else srcsym
                if "source-module" in obj:
                    if obj["source-module"].is_array:
                        path_arr = obj["source-module"].value_array()
                        srcmod, path = parse_path(path_arr)
                    else:
                        srcmod = path = None
                else:
                    srcmod = "#%kernel"
                    path   = None
                return ModuleVar(modsym, srcmod, srcsym, path=path)
            if "lexical" in obj:
                return LexicalVar(mksym(obj["lexical"].value_string()))
            if "toplevel" in obj:
                return ToplevelVar(mksym(obj["toplevel"].value_string()))
            if "module-name" in obj:
                return self.to_module(json)
        assert 0, "Unexpected json object: %s" % json.tostring()

VOID = Quote(values.w_void)

def _to_num(json):
    assert json.is_object
    obj = json.value_object()
    if "real" in obj:
        r = obj["real"]
        return values.W_Flonum.make(r.value_float())
    if "real-part" in obj:
        r = obj["real-part"]
        i = obj["imag-part"]
        return values.W_Complex.make(_to_num(r), _to_num(i))
    if "numerator" in obj:
        n = obj["numerator"]
        d = obj["denominator"]
        return values.W_Rational.make(_to_num(n), _to_num(d))
    if "extended-real" in obj:
        rs = obj["extended-real"].value_string()
        if rs == "+inf.0":
            return values.W_Flonum.INF
        if rs == "-inf.0":
            return values.W_Flonum.NEGINF
        if rs == "+nan.0":
            return values.W_Flonum.NAN
    if "integer" in obj:
        rs = obj["integer"].value_string()
        try:
            return values.W_Fixnum.make(string_to_int(rs))
        except ParseStringOverflowError:
            val = rbigint.fromdecimalstr(rs)
            return values.W_Bignum(val)
    assert False

def decode_byte_array(arr):
    return [chr(i.value_int()) for i in arr.value_array()]

def to_value(json):
    dbgprint("to_value", json)
    if json is pycket_json.json_false:
        return values.w_false
    elif json is pycket_json.json_true:
        return values.w_true
    if json.is_object:
        # The json-object should only contain one element
        obj = json.value_object()
        if "vector" in obj:
            return vector.W_Vector.fromelements([to_value(v) for v in obj["vector"].value_array()], immutable=True)
        if "struct" in obj:
            key = to_value(obj["prefab-key"])
            fields = [to_value(v) for v in obj["struct"].value_array()]
            return values_struct.W_Struct.make_prefab(key, fields)
        if "box" in obj:
            return values.W_IBox(to_value(obj["box"]))
        if "number" in obj:
            return _to_num(obj["number"])
        if "path" in obj:
            return values.W_Path(obj["path"].value_string())
        if "char" in obj:
            return values.W_Character.make(unichr(int(obj["char"].value_string())))
        if "hash-keys" in obj and "hash-vals" in obj:
            keys = [to_value(i) for i in obj["hash-keys"].value_array()]
            vals = [to_value(i) for i in obj["hash-vals"].value_array()]
            return make_simple_immutable_table(W_EqualImmutableHashTable, keys, vals)
        if "regexp" in obj:
            return values_regex.W_Regexp(obj["regexp"].value_string())
        if "byte-regexp" in obj:
            arr = decode_byte_array(obj["byte-regexp"])
            return values_regex.W_ByteRegexp("".join(arr))
        if "pregexp" in obj:
            return values_regex.W_PRegexp(obj["pregexp"].value_string())
        if "byte-pregexp" in obj:
            arr = decode_byte_array(obj["byte-pregexp"])
            return values_regex.W_BytePRegexp("".join(arr))
        if "bytes" in obj:
            arr = decode_byte_array(obj["bytes"])
            return values.W_ImmutableBytes(arr)
        if "string" in obj:
            return values_string.W_String.make(str(obj["string"].value_string()))
        if "keyword" in obj:
            return values.W_Keyword.make(str(obj["keyword"].value_string()))
        if "improper" in obj:
            improper = obj["improper"].value_array()
            return values.to_improper([to_value(v) for v in improper[0].value_array()], to_value(improper[1]))
        for i in ["toplevel", "lexical", "module", "source-name"]:
            if i in obj:
                return values.W_Symbol.make(obj[i].value_string())
    if json.is_array:
        return values.to_list([to_value(j) for j in json.value_array()])
    assert 0, "Unexpected json value: %s" % json.tostring()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        print parse_module(expand_file(sys.argv[1])).tostring()
