import pytest
from pycket.interpreter import *
from pycket.values import *
from pycket.prims import *
from pycket.test.testhelper import run_fix, run, run_top, run_std
from pycket.error import SchemeException


def test_mul_zero():
    run_fix("(* 0 1.2)", 0)
    run_fix("(* 1.2 0)", 0)

def test_quotient():
    run_fix("(quotient 0 1)", 0)
    run_fix("(quotient 0 -1)", 0)
    run_fix("(quotient 0 2)", 0)
    run_fix("(quotient 0 -2)", 0)
    run_fix("(quotient 0 3)", 0)
    run_fix("(quotient 1 1)", 1)
    run_fix("(quotient -1 1)", -1)
    run_fix("(quotient 1 -1)", -1)
    run_fix("(quotient -1 -1)", 1)
    run_fix("(quotient 1 2)", 0)
    run_fix("(quotient -1 2)", 0)
    run_fix("(quotient 1 -2)", 0)
    run_fix("(quotient -1 -2)", 0)
    run_fix("(quotient -1234 -10)", 123)
    run_fix("(quotient 1234 1234)", 1)
    big = 2 ** 70
    run_fix("(quotient %s %s)" % (big, big), 1)
    run_fix("(quotient %s %s)" % (-big, big), -1)
    run_fix("(quotient %s %s)" % (big, -big), -1)
    run_fix("(quotient %s %s)" % (-big, -big), 1)
    run_fix("(quotient %s %s)" % (big+1, big), 1)
    run_fix("(quotient %s %s)" % (-(big+1), big), -1)
    res = run(str(big / 2))
    run("(quotient %s 2)" % (big, ), res)

def test_div_fix():
    run_fix("(/ 6 3)", 2)
    with pytest.raises(SchemeException):
        run("(/ 1 2)", None) # XXX for now

def test_lt():
    run("(< 0 1)", w_true)
    run("(< 0 1000000000000000000000000000)", w_true)
    run("(< 10000000000000000000000000001000000000000000000000000000 0 )", w_false)

def test_lt_fixnum_flonum():
    run("(< 0 1.0)", w_true)
    run("(< 0 1000000000000000000000000000.0)", w_true)
    run("(< 10000000000000000000000000001000000000000000000000000000 0.0 )", w_false)
    run("(< 0.0 1)", w_true)
    run("(< 0.0 1000000000000000000000000000)", w_true)
    run("(< 10000000000000000000000000001000000000000000000000000000.0 0 )", w_false)

def test_lt_fixnum_bignum():
    run("(< (expt 10 100) 1)", w_false)
    run("(< 1 (expt 10 100))", w_true)

def test_lt_flonum_bignum():
    run("(< (expt 10 100) 1.0)", w_false)
    run("(< 1.0 (expt 10 100))", w_true)

def test_neg_pos():
    run_std("(negative? -1)", w_true)
    run_std("(negative?  0)", w_false)
    run_std("(negative?  1)", w_false)
    run_std("(negative? -1.0)", w_true)
    run_std("(negative?  0.0)", w_false)
    run_std("(negative?  1.0)", w_false)
    run_std("(negative?  -10000000000000000000000000001000000000000000000000000000)", w_true)
    run_std("(negative?   10000000000000000000000000001000000000000000000000000000)", w_false)
    run_std("(positive? -1)", w_false)
    run_std("(positive?  0)", w_false)
    run_std("(positive?  1)", w_true)
    run_std("(positive? -1.0)", w_false)
    run_std("(positive?  0.0)", w_false)
    run_std("(positive?  1.0)", w_true)
    run_std("(positive?  -10000000000000000000000000001000000000000000000000000000)", w_false)
    run_std("(positive?   10000000000000000000000000001000000000000000000000000000)", w_true)

def test_string_to_number(doctest):
    """
    ; not yet supported
    ;> (string->number "3.0+2.5i")
    ;3.0+2.5i
    > (string->number "hello")
    #f
    ;> (string->number "111" 7)
    ;57
    ;> (string->number "#b111" 7)
    ;7
    > (string->number "13")
    13
    > (string->number "-13")
    -13
    > (string->number "-1.3")
    -1.3
    > (string->number "1.3")
    1.3
    > (string->number "-10000000000000000000000000001000000000000000000000000000")
    -10000000000000000000000000001000000000000000000000000000
    > (string->number "10000000000000000000000000001000000000000000000000000000")
    10000000000000000000000000001000000000000000000000000000
    """
    assert doctest
