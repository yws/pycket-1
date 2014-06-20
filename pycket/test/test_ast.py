import pytest
from pycket.expand import expand, expand_string
from pycket.values import W_Symbol
from pycket.expand import _to_ast, to_ast, parse_module
from pycket.interpreter import (LexicalVar, ModuleVar, Done,
                                variable_set, variables_equal,
                                Lambda, Letrec, Let, Quote, App, If,
                                )
from pycket.test.testhelper import format_pycket_mod

def make_symbols(d):
    v = variable_set()
    for i, j in d.iteritems():
        v[ModuleVar(W_Symbol.make(i), None, W_Symbol.make(i))] = j
    return v

def expr_ast(s):
    m = parse_module(expand_string(format_pycket_mod(s, extra="(define x 0)")))
    return m.body[1]

def test_mutvars():
    p = expr_ast("(lambda (x) (set! x 2))")
    assert len(p.mutated_vars()) == 0
    p = expr_ast(("(lambda (y) (set! x 2))"))
    print p
    assert variables_equal(p.mutated_vars(), make_symbols({"x": None}))
    p = expr_ast(("(let ([y 1]) (set! x 2))"))
    assert variables_equal(p.mutated_vars(), make_symbols({"x": None}))
    #    assert p.mutated_vars() == make_symbols({"x": None})
    p = expr_ast(("(let ([x 1]) (set! x 2))"))
    assert variables_equal(p.mutated_vars(), make_symbols({}))

def test_cache_lambda_if_no_frees():
    from pycket.interpreter import ToplevelEnv
    from pycket.values import W_PromotableClosure
    lamb = expr_ast("(lambda (y) (set! y 2))")
    toplevel = ToplevelEnv()
    w_cl1 = lamb.interpret_simple(toplevel)
    assert isinstance(w_cl1, W_PromotableClosure)
    w_cl2 = lamb.interpret_simple(toplevel)
    assert w_cl1 is w_cl2
    assert w_cl1.env.toplevel_env is toplevel

def test_remove_let():
    p = expr_ast("(let ([a 1]) a)")
    assert isinstance(p, Quote)

    p = expr_ast("(let ([g cons]) (g 5 5))")
    assert isinstance(p, App)

    p = expr_ast("(let ([a 1]) (if a + -))")
    assert isinstance(p, If)


def test_reclambda():
    # simple case:
    p = expr_ast("(letrec ([a (lambda () a)]) a)")
    assert isinstance(p, Lambda)
    assert p.recursive_sym is not None

    # immediate application
    p = expr_ast("(letrec ([a (lambda () a)]) (a))")
    assert isinstance(p.rator, Lambda)
    assert p.rator.recursive_sym is not None

    # immediate application
    p = expr_ast("(letrec ([a (lambda (b) (a b))]) (a 1))")
    assert isinstance(p.rator, Lambda)

    # immediate application, need a let because the variable appears not just
    # once (but not a letrec)
    p = expr_ast("(letrec ([a (lambda (b) (a b))]) (a (a 1)))")
    assert isinstance(p, Let)
    assert isinstance(p.rhss[0], Lambda)
    assert p.rhss[0].recursive_sym is not None

def test_cache_closure():
    from pycket import interpreter
    p = expr_ast("(let ([a 1] [b 2] [c 4]) (lambda (x) x a b c))")
    lam = p.body[0]
    lam.recursive_sym = lam.lambody.body[3].sym
    w_closure = lam._make_or_retrieve_closure(interpreter.ConsEnv.make([1, 2, 3, 4], None, None))
    assert 1 in w_closure.env._get_full_list()
    assert 2 in w_closure.env._get_full_list()
    assert w_closure in w_closure.env._get_full_list()

    # check caching
    w_closure1 = lam._make_or_retrieve_closure(interpreter.ConsEnv.make([1, 2, 3, 4], None, None))
    assert w_closure1 is w_closure
    w_closure1 = lam._make_or_retrieve_closure(interpreter.ConsEnv.make([1, 2, 3, 5], None, None))
    assert w_closure1 is w_closure

    # cache invalid:
    w_closure1 = lam._make_or_retrieve_closure(interpreter.ConsEnv.make([7, 2, 3, 5], None, None))
    assert w_closure1 is not w_closure
    # don't attempt to cache again
    w_closure2 = lam._make_or_retrieve_closure(interpreter.ConsEnv.make([7, 2, 3, 5], None, None))
    assert w_closure1 is not w_closure2
