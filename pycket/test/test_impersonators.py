from pycket.test.testhelper import *
from pycket.values import *
from pycket.impersonators import *
from pycket.values_struct import *
import pytest

# This test ensures the new property based on this change to Racket:
# http://git.racket-lang.org/plt/commit/0b71b8481dcf0c8eb99edf5fef9bfdfeb4f92465
def test_chaperone_struct_self_arg():
    m = run_mod(
    """
    #lang pycket
    (struct point (x y))
    (define p (point 1 2))
    (define cell #f)
    (define p-chap
      (chaperone-struct p
        point-x (lambda (self val) (set! cell self) val)))
    (point-x p-chap)
    """)
    prox = m.defs[W_Symbol.make("p")]
    chap = m.defs[W_Symbol.make("p-chap")]
    cell = m.defs[W_Symbol.make("cell")]
    assert isinstance(prox, W_Struct)
    assert isinstance(cell, W_Cell)
    assert isinstance(chap, W_ChpStruct)
    self = cell.get_val()
    #assert self is not prox
    assert self is chap

def test_noninterposing_chaperone():
    m = run_mod(
    """
    #lang pycket
    (define-values (prop:blue blue? blue-ref) (make-impersonator-property 'blue))
    (define-values (prop:green green? green-ref) (make-struct-type-property 'green 'can-impersonate))
    (define a-equal+hash (list
                         (lambda (v1 v2 equal?)
                           (equal? (aa-y v1) (aa-y v2)))
                         (lambda (v1 hash)
                           (hash (aa-y v1)))
                         (lambda (v2 hash)
                           (hash (aa-y v2)))))
    (define (a-impersonator-of v) (a-x v))
    (define (aa-y v) (if (a? v) (a-y v) (pre-a-y v)))
      (define-struct pre-a (x y)
        #:property prop:equal+hash a-equal+hash
        #:property prop:green 'color)
      (define-struct a (x y)
        #:property prop:impersonator-of a-impersonator-of
        #:property prop:equal+hash a-equal+hash)
      (define-struct (a-more a) (z))
      (define-struct (a-new-impersonator a) ()
        #:property prop:impersonator-of a-impersonator-of)
      (define-struct (a-new-equal a) ()
        #:property prop:equal+hash a-equal+hash)
    (define a-pre-a (chaperone-struct (make-pre-a 17 1) pre-a-y (lambda (a v) v)))
    (define t1 (chaperone-of? a-pre-a a-pre-a))
    (define t2
      (chaperone-of?
        (make-pre-a 17 1)
        (chaperone-struct (make-pre-a 17 1) pre-a-y #f prop:blue 'color)))
    (define t3
      (chaperone-of?
        (make-pre-a 17 1)
        (chaperone-struct a-pre-a pre-a-y #f prop:blue 'color)))
    (define t4
      (chaperone-of? a-pre-a
        (chaperone-struct a-pre-a pre-a-y #f prop:blue 'color)))
    (define t5
      (chaperone-of?
        (chaperone-struct a-pre-a pre-a-y #f prop:blue 'color)
        a-pre-a))
    (define t6
      (chaperone-of?
        a-pre-a
        (chaperone-struct a-pre-a pre-a-y (lambda (a v) v) prop:blue 'color)))
    (define t7
      (chaperone-of? a-pre-a
        (chaperone-struct a-pre-a green-ref (lambda (a v) v))))
    """)
    assert m.defs[W_Symbol.make("t1")] is w_true
    assert m.defs[W_Symbol.make("t2")] is w_true
    assert m.defs[W_Symbol.make("t3")] is w_false
    assert m.defs[W_Symbol.make("t4")] is w_true
    assert m.defs[W_Symbol.make("t5")] is w_true
    assert m.defs[W_Symbol.make("t6")] is w_false
    assert m.defs[W_Symbol.make("t7")] is w_false
