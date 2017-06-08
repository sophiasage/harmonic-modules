# -*- coding: utf-8 -*-
import datetime
import inspect
import functools
import operator
import os
import sage.misc.persist as persist

from sage.misc.cachefunc import cached_method, cached_function
from sage.misc.misc_c import prod

from sage.categories.sets_cat import Sets
from sage.categories.algebras import Algebras
from sage.categories.cartesian_product import cartesian_product
from sage.categories.tensor import tensor

from sage.structure.element import have_same_parent
from sage.structure.element_wrapper import ElementWrapper
from sage.structure.parent import Parent

from sage.structure.unique_representation import UniqueRepresentation

from sage.combinat.free_module import CombinatorialFreeModule
from sage.combinat.partition import Partition, Partitions
from sage.combinat.ranker import rank_from_list
from sage.combinat.sf.sf import SymmetricFunctions
from sage.combinat.tableau import StandardTableaux
import sage.combinat.tableau
from sage.combinat.words.word import Word

from sage.groups.perm_gps.permgroup_named import SymmetricGroup
from sage.groups.perm_gps.permgroup_element import PermutationGroupElement
from sage.matrix.constructor import matrix
from sage.modules.free_module_element import vector
from sage.rings.integer_ring import ZZ
from sage.rings.rational_field import QQ
from sage.rings.polynomial.polynomial_ring_constructor import PolynomialRing
from sage.rings.polynomial.polydict import ETuple
from sage.rings.semirings.non_negative_integer_semiring import NN
from sage.sets.recursively_enumerated_set import RecursivelyEnumeratedSet

from sage.functions.other import factorial

class func_persist:
    r"""
    Put ``@func_persist`` right before your function
    definition to cache values it computes to disk.
    """
    def __init__(self, f, dir='func_persist', prefix=None, hash=hash, key=None):
        from sage.misc.misc import sage_makedirs
        self._func = f
        self._dir  = dir
        if prefix is None:
            prefix = f.__name__
        self._prefix = dir+"/"+prefix
        self._hash = hash
        if key is not None:
            self.key = key
        sage_makedirs(dir)
        self.__doc__ = '%s%s%s'%(\
            f.__name__,
            inspect.formatargspec(*inspect.getargs(f.__code__)),
            f.__doc__)

    def key(self, *args, **kwds):
        return (tuple(args), tuple(kwds.items()))

    def __call__(self, *args, **kwds):
        key = self.key(*args, **kwds)
        h = self._hash(key)
        name = '%s_%s.sobj'%(self._prefix, h)

        if os.path.exists(name):
            key2, val = persist.load(name)
            if key == key2:
                # We save and test equality of keys to avoid
                # the (extremely remote) possibility of a hash
                # collision.  Correctness is crucial in mathematics.
                return val

        val = self._func(*args, **kwds)
        persist.save((key, val), name)
        return val

    def dict(self):
        """
        Return the already computed values
        """
        import glob
        return dict(persist.load(name)
                    for name in glob.glob("%s*.sobj"%self._prefix))

def items_of_vector(v):
    """
    Return an iterator over the pairs ``(index, coefficient)`` for `v`.

    INPUT::

    - ``v`` -- an element of some some vector space or free module

    EXAMPLES:

    This handles indexed free module elements::

        sage: E = CombinatorialFreeModule(QQ, [1,2,4,8,16])
        sage: v = E.an_element(); v
        2*B[1] + 2*B[2] + 3*B[4]
        sage: list(items_of_vector(v))
        [(1, 2), (2, 2), (4, 3)]

    free module elements::

        sage: v = vector([4,0,1,2])
        sage: list(items_of_vector(v))
        [(0, 4), (2, 1), (3, 2)]

        sage: v = vector([4,0,1,2], sparse=True)
        sage: list(items_of_vector(v))
        [(0, 4), (2, 1), (3, 2)]

    multivariate polynomials::

        sage: P = QQ['x,y,z']
        sage: x,y,z = P.gens()
        sage: p = (x+y+1)^2; p
        x^2 + 2*x*y + y^2 + 2*x + 2*y + 1
        sage: list(items_of_vector(p))
        [((1, 0, 0), 2),
         ((1, 1, 0), 2),
         ((0, 0, 0), 1),
         ((2, 0, 0), 1),
         ((0, 1, 0), 2),
         ((0, 2, 0), 1)]

    univariate polynomials::

        sage: P = ZZ['x']
        sage: x = P.gen()
        sage: (x+2)^3
        x^3 + 6*x^2 + 12*x + 8
        sage: list(items_of_vector(_))
        [(0, 8), (1, 12), (2, 6), (3, 1)]

    elements of quotients::

        sage: C = CyclotomicField(5)
        sage: z = C.gen()
        sage: p = (z+2)^2; p
        zeta5^2 + 4*zeta5 + 4
        sage: list(items_of_vector(p))
        [(0, 4), (1, 4), (2, 1)]
    """
    if isinstance(v, CombinatorialFreeModule.Element):
        return v
    else:
        try:
            return v.dict().items()
        except AttributeError:
            return items_of_vector(v.lift())

class MatrixOfVectors:
    """
    A mutable data structure representing a collection of vectors as a matrix

    EXAMPLES::

        sage: R = PolynomialRing(QQ, 'x,y,z')
        sage: x,y,z = R.gens()
        sage: M = MatrixOfVectors([x, 2*z, x*y+z, 2*x+z+x*y]); M
        A 4x3 matrix of vectors in Multivariate Polynomial Ring in x, y, z over Rational Field
        sage: M._matrix
        [1 0 0]
        [0 2 0]
        [0 1 1]
        [2 1 1]
    """
    def __init__(self, vectors=None, ambient=None, stats={}):
        if vectors is None and not isinstance(ambient, Parent):
            vectors = ambient
            ambient = None
        if ambient is None:
            if vectors is not None:
                ambient = vectors[0].parent()
        self._ambient = ambient
        self._base_ring = ambient.base_ring()
        self._rank, self._unrank = sage.combinat.ranker.on_fly()
        self._matrix = matrix(self._base_ring, 0, 0)
        self._basis = []
        self._is_echelon = True
        stats.setdefault("add_vector", 0)
        stats.setdefault("extend", 0)
        stats.setdefault("dimension", 0)
        self._stats = stats
        if vectors:
            for v in vectors:
                self.add_vector(v)

    def __repr__(self):
        """

        EXAMPLES::

            sage: E = CombinatorialFreeModule(QQ, [1,2,4,8,16])
            sage: M = EchelonMatrixOfVectors(E); M
            A 0x0 echelon matrix of vectors in Free module generated by {1, 2, 4, 8, 16} over Rational Field
            sage: M.extend(E.an_element())
            True
            sage: M
            A 1x3 echelon matrix of vectors in Free module generated by {1, 2, 4, 8, 16} over Rational Field
        """
        m = self._matrix
        return "A %sx%s matrix of vectors in %s"%(m.nrows(), m.ncols(), self.ambient())

    def ambient(self):
        return self._ambient

    def plain_vector(self, v):
        """
        Return `v` as a plain vector

        INPUT:

        - ``v`` -- an element of the ambient space

        Invariant: when it's returned, the length of the vector is the
        number of basis elements ranked, which is at least the number
        of columns of the matrix.
        """
        # TODO:
        # - optimize this
        # - implement and use a generic api to recover the items
        if not self._ambient.is_parent_of(v):
            raise ValueError("Expected vector in %s; got %s"%(self._ambient, v))
        rank = self._rank
        d = dict((rank(i), c) for i, c in items_of_vector(v))
        return vector(self._base_ring, len(self._rank.cache), d, sparse=False)

    def _add_vector_to_matrix(self, m, v):
        r = self.plain_vector(v)
        if len(r) > m.ncols():
            m = m.augment(matrix(self._base_ring, m.nrows(), len(r)-m.ncols()))
        return m.stack(r)

    def add_vector(self, v):
        """
        Add `v` at the bottom of ``self``
        """
        self._stats["add_vector"] += 1
        self._is_echelon = False
        self._matrix = self._add_vector_to_matrix(self._matrix, v)

class EchelonMatrixOfVectors(MatrixOfVectors):
    """
    A mutable data structure representing a collection of vectors in row echelon form
    """

    def __repr__(self):
        """

        EXAMPLES::

            sage: E = CombinatorialFreeModule(QQ, [1,2,4,8,16])
            sage: M = EchelonMatrixOfVectors(E); M
            A 0x0 echelon matrix of vectors in Free module generated by {1, 2, 4, 8, 16} over Rational Field
            sage: M.extend(E.an_element())
            True
            sage: M
            A 1x3 echelon matrix of vectors in Free module generated by {1, 2, 4, 8, 16} over Rational Field
        """
        m = self._matrix
        return "A %sx%s echelon matrix of vectors in %s"%(m.nrows(), m.ncols(), self.ambient())

    def extend(self, v):
        self._stats["extend"] += 1
        assert self._is_echelon
        m = self._add_vector_to_matrix(self._matrix, v)
        m.echelonize()
        if m[-1]:
            self._stats['dimension'] += 1
            self._matrix = m
            self._basis.append(v)
            return True
        return False

    def cardinality(self):
        return self._matrix.nrows()

def annihilator_basis(B, S, action=operator.mul, side='right', ambient=None):
    """
    A generalization of :meth:`Modules.FiniteDimensional.WithBasis.ParentMethods.annihilator_basis`

    Return a basis of the annihilator of a finite set of elements in the span of ``B``

    INPUT:

    - ``B`` -- a finite iterable of vectors (linearly independent???)

    - ``S`` -- a finite iterable of objects

    - ``action`` -- a function (default: :obj:`operator.mul`)

    - ``side`` -- 'left' or 'right' (default: 'right'):
      on which side of ``self`` the elements of `S` acts.

    See :meth:`annihilator` for the assumptions and definition
    of the annihilator.

    EXAMPLES:

    By default, the action is the standard `*` operation. So
    our first example is about an algebra::

        sage: F = FiniteDimensionalAlgebrasWithBasis(QQ).example(); F
        An example of a finite dimensional algebra with basis:
        the path algebra of the Kronecker quiver
        (containing the arrows a:x->y and b:x->y) over Rational Field
        sage: x,y,a,b = F.basis()

    In this algebra, multiplication on the right by `x`
    annihilates all basis elements but `x`::

        sage: x*x, y*x, a*x, b*x
        (x, 0, 0, 0)

    So the annihilator is the subspace spanned by `y`, `a`, and `b`::

        sage: annihilator_basis(F.basis(), [x])
        (y, a, b)

    The same holds for `a` and `b`::

        sage: x*a, y*a, a*a, b*a
        (a, 0, 0, 0)
        sage: annihilator_basis(F.basis(), [a])
        (y, a, b)

    On the other hand, `y` annihilates only `x`::

        sage: annihilator_basis(F.basis(), [y])
        (x,)

    Here is a non trivial annihilator::

        sage: annihilator_basis(F.basis(), [a + 3*b + 2*y])
        (-1/2*a - 3/2*b + x,)

    Let's check it::

        sage: (-1/2*a - 3/2*b + x) * (a + 3*b + 2*y)
        0

    Doing the same calculations on the left exchanges the
    roles of `x` and `y`::

        sage: annihilator_basis(F.basis(), [y], side="left")
        (x, a, b)
        sage: annihilator_basis(F.basis(), [a], side="left")
        (x, a, b)
        sage: annihilator_basis(F.basis(), [b], side="left")
        (x, a, b)
        sage: annihilator_basis(F.basis(), [x], side="left")
        (y,)
        sage: annihilator_basis(F.basis(), [a+3*b+2*x], side="left")
        (-1/2*a - 3/2*b + y,)

    By specifying an inner product, this method can be used to
    compute the orthogonal of a subspace::

        sage: x,y,a,b = F.basis()
        sage: def scalar(u,v): return vector([sum(u[i]*v[i] for i in F.basis().keys())])
        sage: annihilator_basis(F.basis(), [x+y, a+b], scalar)
        (x - y, a - b)

    By specifying the standard Lie bracket as action, one can
    compute the commutator of a subspace of `F`::

        sage: annihilator_basis(F.basis(), [a+b], action=F.bracket)
        (x + y, a, b)

    In particular one can compute a basis of the center of the
    algebra. In our example, it is reduced to the identity::

        sage: annihilator_basis(F.basis(), F.algebra_generators(), action=F.bracket)
        (x + y,)

    But see also
    :meth:`FiniteDimensionalAlgebrasWithBasis.ParentMethods.center_basis`.
    """
    if side == 'right':
        action_left = action
        action = lambda b,s: action_left(s, b)
    B = list(B)
    if ambient is None:
        ambient = B[0].parent()
    mat = matrix(ambient.base_ring(), len(B), 0)

    for s in S:
        mat = mat.augment(
            MatrixOfVectors([action(s, b) for b in B], ambient=ambient)._matrix)

    return tuple(sum(c * B[i] for i,c in v.iteritems())
                 for v in mat.left_kernel().basis())


class Subspace:
    """
    Construct a subspace from generators and linear operators

    INPUT:

    - ``generators`` -- a list of vectors in some ambient vector space `V`
    - ``operators`` -- a list of linear endomorphism `V` (default: ``[]``)

    Return the smallest subspace of `V` containing ``generators`` and
    stable under the action of the operators.

    EXAMPLES::

        sage: E = CombinatorialFreeModule(QQ, [1,2,4,8,16])
        sage: v = E.an_element(); v
        2*B[1] + 2*B[2] + 3*B[4]
        sage: F = Subspace([v, v], [])
        sage: F.dimension()
        1

        sage: B = E.basis()
        sage: F = Subspace([B[1]-B[2], B[2]-B[4], B[1]-B[4]])
        sage: F.dimension()
        2
        sage: F.matrix()
        [ 1  0 -1]
        [ 0  1 -1]

        sage: E = CombinatorialFreeModule(QQ, [1,2,4,8,16])
        sage: B = E.basis()
        sage: phi = E.module_morphism(lambda i: B[i]+B[2*i] if i <= 8 else E.zero(), codomain=E)
        sage: F = Subspace([phi(B[1])], [phi])
        sage: F.dimension()
        4
        sage: F.matrix()
        [ 1  0  0  0 -1]
        [ 0  1  0  0  1]
        [ 0  0  1  0 -1]
        [ 0  0  0  1  1]

    Computing a subspace of a multivariate polynomial ring::

        sage: P = QQ['x,y,z']
        sage: x,y,z = P.gens()
        sage: F = Subspace([x-y, y-z, x-z])
        sage: F.dimension()
        2
        sage: F.matrix()
        [ 1  0 -1]
        [ 0  1 -1]

    The derivatives of the Van-der-Monde determinant in `n` variables
    spans a space of dimension `n!`::

        sage: Delta = (x-y)*(y-z)*(x-z)
        sage: F = Subspace([Delta], [attrcall("derivative", x) for x in P.gens()])
        sage: F.dimension()
        6

    Computing subalgebras and modules in the algebra of the symmetric
    group::

        sage: S = SymmetricGroup(4)
        sage: A = S.algebra(QQ)
        sage: F = Subspace([A.one()], [functools.partial(operator.mul, A.jucys_murphy(i)) for i in range(1,4)])
        sage: F.dimension()
        4
        sage: F.matrix()
        [1 0 0 0 0 0]
        [0 1 1 0 0 0]
        [0 0 0 1 1 0]
        [0 0 0 0 0 1]

        sage: T = StandardTableaux(4)
        sage: def young_idempotent(t):
        ....:     return A.sum_of_terms((S(sigma), sigma.sign()) for sigma in t.column_stabilizer()) * \
        ....:            A.sum_of_monomials(S(sigma) for sigma in t.row_stabilizer())

        sage: for t in T:
        ....:     print t.shape(), t.shape().dimension(), \
        ....:          Subspace([young_idempotent(t)], \
        ....:                   [functools.partial(operator.mul, s) for s in A.algebra_generators()]).dimension()
        [4] 1 1
        [3, 1] 3 3
        [3, 1] 3 3
        [3, 1] 3 3
        [2, 2] 2 2
        [2, 2] 2 2
        [2, 1, 1] 3 3
        [2, 1, 1] 3 3
        [2, 1, 1] 3 3
        [1, 1, 1, 1] 1 1


    Redoing the derivatives of the Van-der-Monde determinant in `n` variables
    as a graded subspace::

        sage: def add_degrees(d1, d2):
        ....:     d = d1 + d2
        ....:     if d < 0: raise ValueError("Negative degree")
        ....:     return d
        sage: P = QQ['x,y,z']
        sage: x,y,z = P.gens()
        sage: Delta = (x-y)*(y-z)*(x-z)
        sage: F = Subspace(generators={3:[Delta]},
        ....:              operators={-1:[attrcall("derivative", x) for x in P.gens()]},
        ....:              add_degrees=add_degrees)
        sage: F.dimension()
        6
        sage: F.dimensions()
        {0: 1, 1: 2, 2: 2, 3: 1}
        sage: F.hilbert_polynomial()
        q^3 + 2*q^2 + 2*q + 1

        sage: P = QQ['x,y,z,t']
        sage: x,y,z,t = P.gens()
        sage: Delta = apply_young_idempotent(x^3*y^2*z, Partition([1,1,1,1]))
        sage: F = Subspace(generators={6:[Delta]},
        ....:              operators={-1:[attrcall("derivative", x) for x in P.gens()]},
        ....:              add_degrees=add_degrees)
        sage: F.hilbert_polynomial()
        q^6 + 3*q^5 + 5*q^4 + 6*q^3 + 5*q^2 + 3*q + 1
        sage: sage.combinat.q_analogues.q_factorial(4)
        q^6 + 3*q^5 + 5*q^4 + 6*q^3 + 5*q^2 + 3*q + 1
    """

    def __init__(self, generators, operators=[],
                 add_degrees=operator.add,
                 hilbert_parent=None,
                 verbose=False):
        self._stats={}
        self._verbose=verbose

        if not isinstance(generators, dict):
            generators = {0: generators}
        self._generators = generators

        ambient = {g.parent() for gens in generators.values() for g in gens}
        assert len(ambient) == 1
        ambient = ambient.pop()
        self._ambient = ambient
        self._base_ring = ambient.base_ring()

        if hilbert_parent is None:
            if generators.keys()[0] in NN:
                hilbert_parent = QQ['q']
        self._hilbert_parent = hilbert_parent

        if not isinstance(operators, dict):
            operators = {0: operators}
        self._operators = operators

        self._bases = {}
        self._todo = []
        self._add_degrees = add_degrees
        for d, gens in generators.iteritems():
            basis = EchelonMatrixOfVectors(ambient=self._ambient, stats=self._stats)
            gens = [v
                    for v in gens
                    if basis.extend(v)]
            self._bases[d] = basis
            self.todo(d, gens)

    def todo(self, d1, vectors):
        todo = self._todo
        for d2, ops in self._operators.iteritems():
            try:
                d3 = self._add_degrees(d1, d2)
            except ValueError:
                continue
            todo.extend((v, d3, op)
                        for v in vectors
                        for op in ops)

    def dimension(self):
        """

        """
        self.finalize()
        return sum(basis.cardinality() for basis in self._bases.values())


    def hilbert_polynomial(self):
        return self._hilbert_parent(self.dimensions())

    def dimensions(self):
        self.finalize()
        return {d: basis.cardinality() for d, basis in self._bases.iteritems()}


    def matrix(self):
        self.finalize()
        assert self._bases.keys() == [0] # only handle the non graded case
        return self._bases[0]._matrix

    @cached_method
    def finalize(self):
        todo = self._todo
        if not todo:
            return
        if self._verbose:
            import progressbar
            bar = progressbar.ProgressBar(max_value=progressbar.UnknownLength)
        while todo:
            v,d,op = todo.pop()
            w = op(v)
            if d not in self._bases:
                self._bases[d] = EchelonMatrixOfVectors(ambient=self._ambient, stats=self._stats)
            if self._bases[d].extend(w):
                self.todo(d, [w])
            if self._verbose:
                bar.update(len(todo)),
        if self._verbose:
            bar.finish()
            print "  dimension: %s  extensions: %s"%(self._stats["dimension"], self._stats["extend"])

def destandardize(self):
    """
    Return the smallest word whose standard permutation is ``self``

    INPUT:

    - ``self`` -- a permutation of 1...n

    OUTPUT: a word in the alphabet 0,...,

    EXAMPLES::

        sage: for p in Permutations(3): print(p, destandardize(p))
        ([1, 2, 3], [0, 0, 0])
        ([1, 3, 2], [0, 1, 0])
        ([2, 1, 3], [1, 0, 1])
        ([2, 3, 1], [1, 1, 0])
        ([3, 1, 2], [1, 0, 0])
        ([3, 2, 1], [2, 1, 0])

        sage: for p in Permutations(4):
        ....:     assert Word(destandardize(p)).standard_permutation() == p
    """
    n = len(self)
    sigma = ~self
    c = 0
    w = [None] * n
    for i in range(1,n+1):
        w[sigma(i)-1] = c
        if i < n and sigma(i+1) < sigma(i):
            c += 1
    return w

def index_filling(t):
    """
    Return the index filling of this standard tableau.

    INPUT:

    - ``t`` -- a standard tableau

    The index filling of `t` is the semi standard tableau with lowest
    content whose standardized row reading coincides with the row
    reading of `t`.

    Reference: Higher Specht Polynomials for the symmetric group and
    the wreath product, S.  Ariki, T.  Terasoma, H.  Yamada.

    Note: in the above reference, the reading word is instead the
    reverse of the row reading of the transpose of `t`.

    .. TODO::

        Check whether this is the most desirable convention.

    EXAMPLES::

        sage: Tableaux.options.convention="french"

        sage: t = StandardTableau([[1,2,4], [3,5]])
        sage: ascii_art(t, index_filling(t), sep = "  -->  ")
          3  5            1  2
          1  2  4  -->    0  0  1

        sage: for t in StandardTableaux([3,2,1]):
        ....:     print ascii_art(t,  index_filling(t), sep="  -->  "); print
          3               2
          2  5            1  3
          1  4  6  -->    0  2  3
        <BLANKLINE>
          4               2
          2  5            1  2
          1  3  6  -->    0  1  2
        <BLANKLINE>
          4               2
          3  5            1  2
          1  2  6  -->    0  0  2
        ...
          6               3
          2  4            1  2
          1  3  5  -->    0  1  2
        ...
          6               2
          4  5            1  1
          1  2  3  -->    0  0  0

    The sum of the entries of the index filling is the cocharge of `t`::

        sage: for t in StandardTableaux(6):
        ....:     assert t.cocharge() == sum(i for row in index_filling(t) for i in row)
    """
    return sage.combinat.tableau.from_shape_and_word(t.shape(), destandardize(t.reading_word_permutation()))

def apply_young_idempotent(p, t, use_antisymmetry=False):
    """
    Apply the Young idempotent indexed by `t` on the polynomial `p`

    INPUT::

    - `t` -- a standard tableau or a partition
    - `p` -- a polynomial on as many variables as there are cells in `t`

    The Young idempotent first symmetrizes `p` according to the
    row stabilizer of `t` and then antisymmetrizes the result according
    to the column stabilizer of `t` (a cell containing `i` in `t`
    being associated to the `i`-th variable (starting at `i=1`)
    of the polynomial ring containing `p`.

    .. TODO:: normalize result

    EXAMPLES::

        sage: x,y,z = QQ['x,y,z'].gens()
        sage: p = x^2 * y
        sage: t = StandardTableau([[1],[2],[3]])
        sage: apply_young_idempotent(p, t)
        x^2*y - x*y^2 - x^2*z + y^2*z + x*z^2 - y*z^2

        sage: apply_young_idempotent(p, Partition([1,1,1]))
        x^2*y - x*y^2 - x^2*z + y^2*z + x*z^2 - y*z^2

        sage: t = StandardTableau([[1,2,3]])
        sage: apply_young_idempotent(p, t)
        x^2*y + x*y^2 + x^2*z + y^2*z + x*z^2 + y*z^2

        sage: apply_young_idempotent(p, Partition([3]))
        x^2*y + x*y^2 + x^2*z + y^2*z + x*z^2 + y*z^2

        sage: t = StandardTableau([[1,2],[3]])
        sage: p = x*y*y^2
        sage: apply_young_idempotent(p, t)
        x^3*y + x*y^3 - y^3*z - y*z^3

        sage: p = x*y*z^2
        sage: apply_young_idempotent(p, t)
        -2*x^2*y*z + 2*x*y*z^2
    """
    if isinstance(t, Partition):
        t = t.initial_tableau()
    p = sum( p*sigma for sigma in t.row_stabilizer() )
    if use_antisymmetry:
        antisymmetries = antisymmetries_of_tableau(t)
        p = antisymmetric_normal(p, t.size(), 1, antisymmetries)
    else:
        p = sum( p*sigma*sigma.sign() for sigma in t.column_stabilizer() )
    return p

def antisymmetries_of_tableau(Q):
    return [[i-1 for i in column] for column in Q.conjugate()]

@cached_function
def higher_specht(R, P, Q=None, harmonic=False, use_antisymmetry=False):
    """
    Return a basis element of the coinvariants

    INPUT:

    - `R` -- a polynomial ring
    - `P` -- a standard tableau of some shape `\lambda`, or a partition `\lambda`
    - `Q` -- a standard tableau of shape `\lambda`
             (default: the initial tableau of shape `\lambda`)

    - ``harmonic`` -- a boolean (default False)

    The family `(H_{P,Q})_{P,Q}` is a basis of the space of `R_{S_n}`
    coinvariants in `R` which is compatible with the action of the
    symmetric group: namely, for each `P`, the family `(H_{P,Q})_Q`
    forms the basis of an `S_n`-irreducible module `V_{P}` of type
    `\lambda`.

    If `P` is a partition `\lambda` or equivalently the initial
    tableau of shape `\lambda`, then `H_{P,Q}` is the usual Specht
    polynomial, and `V_P` the Specht module.

    EXAMPLES::

        sage: Tableaux.options.convention="french"

        sage: R = PolynomialRing(QQ, 'x,y,z')
        sage: for la in Partitions(3):
        ....:     for P in StandardTableaux(la):
        ....:         for Q in StandardTableaux(la):
        ....:             print ascii_art(la, P, Q, factor(higher_specht(R, P, Q)), sep="    ")
        ....:             print
        ***      1  2  3      1  2  3    2 * 3
        <BLANKLINE>
        *       2         2
        **      1  3      1  3    (-1) * z * (x - y)
        <BLANKLINE>
        *       2         3
        **      1  3      1  2    (-1) * y * (x - z)
        <BLANKLINE>
        *       3         2
        **      1  2      1  3    (-2) * (x - y)
        <BLANKLINE>
        *       3         3
        **      1  2      1  2    (-2) * (x - z)
        <BLANKLINE>
        *      3      3
        *      2      2
        *      1      1    (y - z) * (-x + y) * (x - z)

        sage: R = PolynomialRing(QQ, 'x,y,z')
        sage: for la in Partitions(3):
        ....:     for P in StandardTableaux(la):
        ....:         print ascii_art(la, P, factor(higher_specht(R, P)), sep="    ")
        ....:         print
        ***      1  2  3    2 * 3
        <BLANKLINE>
        *       2
        **      1  3    (-1) * y * (x - z)
        <BLANKLINE>
        *       3
        **      1  2    (-2) * (x - z)
        <BLANKLINE>
        *      3
        *      2
        *      1    (y - z) * (-x + y) * (x - z)

        sage: R = PolynomialRing(QQ, 'x,y,z')
        sage: for la in Partitions(3):
        ....:     for P in StandardTableaux(la):
        ....:         for Q in StandardTableaux(la):
        ....:             print ascii_art(la, P, Q, factor(higher_specht(R, P, Q, harmonic=True)), sep="    ")
        ....:             print
        ***      1  2  3      1  2  3    2 * 3
        <BLANKLINE>
        *       2         2
        **      1  3      1  3    (-1/3) * (-x - y + 2*z) * (x - y)
        <BLANKLINE>
        *       2         3
        **      1  3      1  2    (-1/3) * (-x + 2*y - z) * (x - z)
        <BLANKLINE>
        *       3         2
        **      1  2      1  3    (-2) * (x - y)
        <BLANKLINE>
        *       3         3
        **      1  2      1  2    (-2) * (x - z)
        <BLANKLINE>
        *      3      3
        *      2      2
        *      1      1    (y - z) * (-x + y) * (x - z)
        <BLANKLINE>

        sage: R = PolynomialRing(QQ, 'x,y,z')
        sage: for la in Partitions(3):
        ....:     for P in StandardTableaux(la):
        ....:         for Q in StandardTableaux(la):
        ....:             print ascii_art(la, P, Q, factor(higher_specht(R, P, Q, harmonic="dual")), sep="    ")
        ....:             print
        ***      1  2  3      1  2  3    2^2 * 3
        <BLANKLINE>
        *       2         2
        **      1  3      1  3    (-2) * (-x^2 - 2*x*y + 2*y^2 + 4*x*z - 2*y*z - z^2)
        <BLANKLINE>
        *       2         3
        **      1  3      1  2    (-2) * (x^2 - 4*x*y + y^2 + 2*x*z + 2*y*z - 2*z^2)
        <BLANKLINE>
        *       3         2
        **      1  2      1  3    (-2) * (-x + 2*y - z)
        <BLANKLINE>
        *       3         3
        **      1  2      1  2    (-2) * (x + y - 2*z)
        <BLANKLINE>
        *      3      3
        *      2      2
        *      1      1    (6) * (y - z) * (-x + y) * (x - z)
        <BLANKLINE>

    This catched two bugs::

        sage: for mu in Partitions(6):             # long test
        ....:     for t in StandardTableaux(mu):
        ....:         p = R.higher_specht(t, harmonic=True, use_antisymmetry=True)
    """
    n = P.size()
    assert n == R.ngens()
    if Q is None:
        Q = P.shape().initial_tableau()
    if harmonic == "dual":
        # Computes an harmonic polynomial obtained by applying h as
        # differential operator on the van der mond
        P = P.conjugate()
        Q = Q.conjugate() # Is this really what we want?
        h = higher_specht(R, P, Q)
        vdm = higher_specht(R, Partition([1]*n).initial_tableau())
        return polynomial_derivative(h, vdm)
    elif harmonic:
        # TODO: normalization
        n = R.ngens()
        Sym = SymmetricFunctions(R.base_ring())
        m = Sym.m()
        p = Sym.p()
        d = P.cocharge()
        B = [higher_specht(R, P, Q, use_antisymmetry=use_antisymmetry)] + \
            [higher_specht(R, P2, Q, use_antisymmetry=use_antisymmetry) * m[nu].expand(n, R.gens())
             for P2 in StandardTableaux(P.shape()) if P2.cocharge() < d
             for nu in Partitions(d-P2.cocharge(), max_length=n)]
        if use_antisymmetry:
            antisymmetries = antisymmetries_of_tableau(Q)
            B = [antisymmetric_normal(b, n, 1, antisymmetries) for b in B]
        operators = [p[k].expand(n,R.gens()) for k in range(1,n+1)]
        if use_antisymmetry:
            def action(e, f):
                return antisymmetric_normal(polynomial_derivative(e,f), n, 1, antisymmetries)
        else:
            action = polynomial_derivative
        ann = annihilator_basis(B, operators, action=action, side='left')
        assert len(ann) == 1
        return ann[0]

    exponents = index_filling(P)
    X = R.gens()
    m = R.prod(X[i-1]**d for (d,i) in zip(exponents.entries(), Q.entries()))
    return apply_young_idempotent(m, Q, use_antisymmetry=use_antisymmetry)

def reverse_sorting_permutation(t):
    r"""
    Return a permutation `p` such that  is decreasing

    INPUT:

    - `t` -- a list/tuple/... of numbers

    OUTPUT:

    a minimal permutation `p` such that `w \circ p` is sorted decreasingly

    EXAMPLES::

        sage: t = [3, 3, 1, 2]
        sage: s = reverse_sorting_permutation(t); s
        [1, 2, 4, 3]
        sage: [t[s[i]-1] for i in range(len(t))]
        [3, 3, 2, 1]

        sage: t = [4, 2, 3, 2, 1, 3]
        sage: s = reverse_sorting_permutation(t); s
        [1, 3, 6, 2, 4, 5]
        sage: [t[s[i]-1] for i in range(len(t))]
        [4, 3, 3, 2, 2, 1]
    """
    return ~(Word([-i for i in t]).standard_permutation())


def diagonal_swap(exponents, n, r, i1, i2):
    """
    Swap in place two columns.

    INPUT:

    - ``exponents `` -- a list, seen as an `r\times n` array
    - ``r``, ``n`` -- nonnegative integers
    - ``i1``, ``i2`` -- integers in `0,\ldots,n-1`

    Swap inplace the columnss ``i1`` and ``i2`` in the list ``exponnents``,
    seen as an `r\times n` array.

    EXAMPLES::

        sage: l = [1,2,3,4,5,6,7,8]
        sage: diagonal_swap(l, 4, 2, 1, 3)
        sage: l
        [1, 4, 3, 2, 5, 8, 7, 6]

        sage: l = [1,2,3,4,5,6,7,8]
        sage: diagonal_swap(l, 2, 4, 0, 1)
        sage: l
        [2, 1, 4, 3, 6, 5, 8, 7]
    """
    for i in range(r):
        exponents[i*n+i1], exponents[i*n+i2] = exponents[i*n+i2], exponents[i*n+i1]

def diagonal_cmp(exponents, n, r, i1, i2):
    """
    Compare lexicographically two columns.

    INPUT:

    - ``exponents `` -- a list, seen as an `r\times n` array
    - ``r``, ``n`` -- nonnegative integers
    - ``i1``, ``i2`` -- integers in `0,\ldots,n-1`

    Compare lexicographically the columns ``i1`` and ``i2`` in the
    list ``exponnents``, seen as an `r\times n` array.

    EXAMPLES::

        sage: l = [1, 1, 2, 2, 0, 1, 1, 0]
        sage: diagonal_cmp(l, 4, 2, 0, 1)
        -1
        sage: diagonal_cmp(l, 4, 2, 1, 0)
        1
        sage: diagonal_cmp(l, 4, 2, 2, 3)
        1
        sage: diagonal_cmp(l, 4, 2, 3, 2)
        -1
        sage: diagonal_cmp(l, 4, 2, 3, 3)
        0
    """
    for i in range(r):
        c = cmp(exponents[i*n+i1], exponents[i*n+i2])
        if c:
            return c
    return 0

def diagonal_antisort(exponents, n, r, positions_list):
    """
    Sorts columns decreasingly according to positions.

    INPUT:

    - ``exponents `` -- a list, seen as an `r\times n` array
    - ``r``, ``n`` -- nonnegative integers
    - ``positions_list`` -- a list of list of positions

    EXAMPLES::

        sage: diagonal_antisort([2,1], 2, 1, [[0,1]])
        ((2, 1), 1)
        sage: diagonal_antisort([1,2], 2, 1, [[0,1]])
        ((2, 1), -1)
        sage: diagonal_antisort([2,2], 2, 1, [[0,1]])

        sage: diagonal_antisort([1,2,3,4], 2, 2, [[0,1]])
        ((2, 1, 4, 3), -1)
        sage: diagonal_antisort([1,2,4,3], 2, 2, [[0,1]])
        ((2, 1, 3, 4), -1)
        sage: diagonal_antisort([2,1,4,3], 2, 2, [[0,1]])
        ((2, 1, 4, 3), 1)
        sage: diagonal_antisort([2,1,3,4], 2, 2, [[0,1]])
        ((2, 1, 3, 4), 1)

        sage: diagonal_antisort([1,2,3], 3, 1, [[0,1,2]])
        ((3, 2, 1), -1)
        sage: diagonal_antisort([1,3,2], 3, 1, [[0,1,2]])
        ((3, 2, 1), 1)
        sage: diagonal_antisort([3,2,1], 3, 1, [[0,1,2]])
        ((3, 2, 1), 1)
        sage: diagonal_antisort([1,2,3,4,5,6], 6, 1, [[0,2,4]])
        ((5, 2, 3, 4, 1, 6), -1)

    With unsorted list of positions, the order is relative to the
    order of positions::

        sage: diagonal_antisort([1,2,3], 3, 1, [[2,1,0]])
        ((1, 2, 3), 1)
        sage: diagonal_antisort([3,2,1], 3, 1, [[2,1,0]])
        ((1, 2, 3), -1)

    Two lists of positions::

        sage: diagonal_antisort([1,2,3,4,5,6], 6, 1, [[0,2,4],[1,3,5]])
        ((5, 6, 3, 4, 1, 2), 1)

    """
    sign = 1
    exponents = list(exponents)
    for positions in positions_list:
        for i in range(1, len(positions)):
            for j in range(i-1, -1, -1):
                c = diagonal_cmp(exponents, n, r, positions[j], positions[j+1])
                if not c:
                    return None
                if c < 0:
                    diagonal_swap(exponents, n, r, positions[j], positions[j+1])
                    sign = -sign
                else:
                    continue
    return ETuple(exponents), sign

def antisymmetric_normal(p, n, r, positions):
    """

    EXAMPLES::

        sage: R = DiagonalPolynomialRing(QQ, 4, 2)
        sage: X = R.algebra_generators()
        sage: p = 2 * X[0,0]*X[0,3]^2*X[1,1]*X[1,0]^3 + X[1,3] + 3
        sage: antisymmetric_normal(p, 4, 2, [[0,1,2,3]])
        -2*x00^2*x01*x11^3*x12

    TODO: check the result

        sage: antisymmetric_normal(p, 4, 2, [[0,1]])
        2*x00*x03^2*x10^3*x11
        sage: antisymmetric_normal(p, 4, 2, [[0,3]])
        -2*x00^2*x03*x11*x13^3 - x10

    An example with a collision in the result (failed at some point)::

        sage: R = DiagonalPolynomialRing(QQ, 3, 3)
        sage: R._P.inject_variables()
        Defining x00, x01, x02, x10, x11, x12, x20, x21, x22
        sage: p1 = -2*x10*x11*x20 - 2*x10^2*x21 + 2*x10*x11*x21
        sage: antisymmetric_normal(p1, 3, 3, [[0,1,2]])
        -4*x10*x11*x20 - 2*x10^2*x21


    """
    R = p.parent()
    d = {}
    for exponent, c in items_of_vector(p):
        res = diagonal_antisort(exponent, n, r, positions)
        if res:
            exponent, sign = res
            d.setdefault(exponent, 0)
            d[exponent] += sign*c
    return R(d)


##############################################################################
# Polynomial ring with diagonal action
##############################################################################

class DiagonalPolynomialRing(UniqueRepresentation, Parent):
    """

    EXAMPLES::

        sage: P = DiagonalPolynomialRing(QQ, 4, 3)
        sage: P.algebra_generators()
        [x00 x01 x02 x03]
        [x10 x11 x12 x13]
        [x20 x21 x22 x23]
    """
    def __init__(self, R, n, r):
        names = ["x%s%s"%(i,j) for i in range(r) for j in range(n)]
        P = PolynomialRing(R, n*r, names)
        self._n = n
        self._r = r
        vars = P.gens()
        self._P = P
        self._grading_set = cartesian_product([ZZ for i in range(r)]) # ZZ^r
        self._hilbert_parent = PolynomialRing(ZZ, r, 'q')
        self._vars = matrix([[vars[i*n+j] for j in range(n)] for i in range(r)])
        Parent.__init__(self, facade=(P,), category=Algebras(QQ).Commutative())

    def _repr_(self):
        """
            sage: DiagonalPolynomialRing(QQ, 5, 3) # indirect doctest
            Diagonal polynomial ring with 3 rows of 5 variables over Rational Field

        """
        return "Diagonal polynomial ring with %s rows of %s variables over %s"%(self._r, self._n, self.base_ring())

    def base_ring(self):
        return self._P.base_ring()

    def algebra_generators(self):
        return self._vars

    def multidegree(self, p):
        """
        Return the multidegree of a multihomogeneous polynomial

        EXAMPLES::

            sage: P = DiagonalPolynomialRing(QQ,3,2)
            sage: X = P.algebra_generators()
            sage: p = X[0,0]*X[0,1]^2 * X[1,0]^2*X[1,1]^3
            sage: P.multidegree(p)
            (3, 5)
            sage: P.multidegree(P.zero())
            -1
        """
        if not p:
            return -1
        n = self._n
        r = self._r
        v = p.exponents()[0]
        return self._grading_set([sum(v[n*i+j] for j in range(n))
                                  for i in range(r)])

    def row_permutation(self, sigma):
        """
        Return the permutation of the variables induced by a permutation of the rows

        INPUT:

        - ``sigma`` -- a permutation of the rows, as a permutation of `\{1,\ldots,r\}`

        OUTPUT:

        a permutation of the variables, as a permutation of `\{1,\ldots,nr\}`

        EXAMPLES::

            sage: s = PermutationGroupElement([(1,2,4),(3,5)])
            sage: P = DiagonalPolynomialRing(QQ,3,5)
            sage: P.row_permutation(s)
            (1,4,10)(2,5,11)(3,6,12)(7,13)(8,14)(9,15)
        """
        n = self._n
        return PermutationGroupElement([tuple((i-1)*n + 1 + j for i in c)
                                        for c in sigma.cycle_tuples()
                                        for j in range(n) ])

    def polarization(self, p, i1, i2, d, use_symmetry=False, antisymmetries=None):
        """

        EXAMPLES::

            sage: P = DiagonalPolynomialRing(QQ, 4, 3)
            sage: X = P.algebra_generators()
            sage: p = X[0,0]*X[1,0]^3*X[1,1]^1 + X[2,1]; p
            x00*x10^3*x11 + x21

            sage: P.polarization(p, 1, 2, 2)
            6*x00*x10*x11*x20
            sage: P.polarization(p, 1, 2, 1)
            3*x00*x10^2*x11*x20 + x00*x10^3*x21

            sage: P.polarization(p, 1, 0, 2)
            6*x00^2*x10*x11

            sage: P.polarization(p, 2, 0, 1)
            x01
        """
        n = self._n
        X = self.algebra_generators()
        result = self.sum(X[i2,j]*p.derivative(X[i1,j],d)
                          for j in range(n))
        if use_symmetry and result:
            d = self.multidegree(result)
            if list(d) != sorted(d, reverse=True):
                s = reverse_sorting_permutation(d)
                ss = self.row_permutation(s)
                result = act_on_polynomial(result, ss)
                #substitution = \
                #    dict(sum((zip(X[s[i]-1], X[i])
                #              for i in range(r) if s[i]-1 != i), []
                #            ))
                #result = result.substitute(substitution)
            Partition(self.multidegree(result))
        if antisymmetries and result:
            result = antisymmetric_normal(result, self._n, self._r, antisymmetries)
        return result

    def polarization_operators_by_degree(self, side=None, use_symmetry=False, antisymmetries=None, min_degree=0):
        """
        Return the collection of polarization operators acting on harmonic polynomials

        INPUT:

        - ``side`` -- 'down'
        - ``min_degree`` -- a non negative integer `d` (default: `0`)

          if `d>0`, only return the polarization operators of differential degree `>=d`.

        If ``side`` is `down` (the only implemented choice), only
        the operators from `X_{i1}` to `X_{i2}` for `i1<i2` are returned.

        EXAMPLES::

            sage: P = DiagonalPolynomialRing(QQ, 4, 2)
            sage: ops = P.polarization_operators_by_degree(); ops
            {(-1, 1): [<functools.partial object at ...>],
             (1, -2): [<functools.partial object at ...>],
             (-2, 1): [<functools.partial object at ...>],
             (-3, 1): [<functools.partial object at ...>],
             (1, -3): [<functools.partial object at ...>],
             (1, -1): [<functools.partial object at ...>]}

            sage: P.polarization_operators_by_degree(side="down")
            {(-3, 1): [<functools.partial object at ...>],
             (-1, 1): [<functools.partial object at ...>],
             (-2, 1): [<functools.partial object at ...>]}

            sage: P = DiagonalPolynomialRing(QQ, 3, 3)
            sage: P.polarization_operators_by_degree(side="down")
            {(-1, 1, 0): [<functools.partial object at ...>],
             (-2, 1, 0): [<functools.partial object at ...>],
             (-2, 0, 1): [<functools.partial object at ...>],
             (0, -2, 1): [<functools.partial object at ...>],
             (-1, 0, 1): [<functools.partial object at ...>],
             (0, -1, 1): [<functools.partial object at ...>]}

            sage: P.polarization_operators_by_degree(use_lie=True)       # not tested
            {(-2, 1, 0): [<functools.partial object at 0x7f6e3235f520>],
             (-2, 0, 1): [<functools.partial object at 0x7f6e3235f5d0>],
             (0, 1, -1): [<functools.partial object at 0x7f6e3235f3c0>],
             (0, -2, 1): [<functools.partial object at 0x7f6e3235f680>],
             (1, -1, 0): [<functools.partial object at 0x7f6e3235f470>]}

            sage: P = DiagonalPolynomialRing(QQ, 4, 3)
            sage: ops = P.polarization_operators_by_degree()
            sage: X = P.algebra_generators()
            sage: p = X[0,0]*X[1,0]^3*X[1,1]^1 + X[2,1]; p
            x00*x10^3*x11 + x21
            sage: ops[(1,-2,0)][0](p)
            6*x00^2*x10*x11
            sage: ops[(0,-1,1)][0](p)
            3*x00*x10^2*x11*x20 + x00*x10^3*x21
        """
        n = self._n
        r = self._r
        grading_set = self._grading_set
        return {grading_set([-d if i==i1 else 1 if i==i2 else 0 for i in range(r)]):
                [functools.partial(self.polarization, i1=i1, i2=i2, d=d, use_symmetry=use_symmetry, antisymmetries=antisymmetries)]
                for d in range(min_degree+1, n)
                for i1 in range(0,r)
                for i2 in range(0, r)
                #if ((i1==i2+1 if d==1 else i1<i2) if use_lie else i1<i2 if side == 'down' else i1!=i2)
                if (i1<i2 if side == 'down' else i1!=i2)
               }

    def higher_specht(self, P, Q=None, harmonic=False, use_antisymmetry=False):
        r"""
        Return the hyper specht polynomial indexed by `P` and `Q` in the first row of variables

        See :func:`higher_specht` for details.

        EXAMPLES::

            sage: R = DiagonalPolynomialRing(QQ, 3, 2)
            sage: R.algebra_generators()
            [x00 x01 x02]
            [x10 x11 x12]

            sage: for la in Partitions(3):
            ....:     for P in StandardTableaux(la):
            ....:         print ascii_art(la, R.higher_specht(P), sep="    ")
            ....:         print
            ....:
            ***    6
            <BLANKLINE>
            *
            **    -x00*x01 + x01*x02
            <BLANKLINE>
            *
            **    -2*x00 + 2*x02
            <BLANKLINE>
            *
            *
            *    -x00^2*x01 + x00*x01^2 + x00^2*x02 - x01^2*x02 - x00*x02^2 + x01*x02^2

            sage: for la in Partitions(3):
            ....:     for P in StandardTableaux(la):
            ....:         print ascii_art(la, R.higher_specht(P, use_antisymmetry=True), sep="    ")
            ....:         print
            ....:
            ***    6
            <BLANKLINE>
            *
            **    -x00*x01
            <BLANKLINE>
            *
            **    -2*x00
            <BLANKLINE>
            *
            *
            *    -x00^2*x01
        """
        X = self.algebra_generators()
        # the self._n forces a multivariate polynomial ring even if n=1
        R = PolynomialRing(self.base_ring(), self._n, list(X[0]))
        H = higher_specht(R, P, Q, harmonic=harmonic, use_antisymmetry=use_antisymmetry)
        return self(H)

    def _add_degree(self, d1,d2):
        d = d1 + d2
        if not all(i>=0 for i in d):
            raise ValueError("invalid degree")
        return d

    def _add_degree_symmetric(self, d1,d2):
        """
        EXAMPLES::

            sage: P = DiagonalPolynomialRing(QQ,4,3)
            sage: D = P._grading_set
            sage: P._add_degree_symmetric(D([3,2,1]), D([-2,0,0]))
            (2, 1, 1)
            sage: P._add_degree_symmetric(D([3,2,1]), D([-2,1,4]))
            (5, 3, 1)
            sage: P._add_degree_symmetric(D([3,2,1]), D([2,1,1]))
            (5, 3, 2)
            sage: P._add_degree_symmetric(D([3,2,1]), D([2,1,-2]))
            Traceback (most recent call last):
            ...
            ValueError: invalid degree
        """
        d = d1 + d2
        if not all(i>=0 for i in d):
            raise ValueError("invalid degree")
        return self._grading_set(sorted(d, reverse=True))

    @cached_method
    def harmonic_space_by_shape(self, mu, verbose=False, use_symmetry=False, use_antisymmetry=False, use_lie=False):
        """
        EXAMPLES::

            sage: P = DiagonalPolynomialRing(QQ,4,2)
            sage: F = P.harmonic_space_by_shape([1,1,1,1])
            sage: F.hilbert_polynomial()
            s[3, 1] + s[4, 1] + s[6]

            sage: P = DiagonalPolynomialRing(QQ,3,2)
            sage: F = P.harmonic_space_by_shape([1,1,1])
            sage: F.hilbert_polynomial()
            s[1, 1] + s[3]

            sage: P = DiagonalPolynomialRing(QQ,3,2)
            sage: F = P.harmonic_space_by_shape([1,1,1])
            sage: F.hilbert_polynomial()
            s[1, 1] + s[3]
        """
        mu = Partition(mu)
        r = self._r
        S = SymmetricFunctions(ZZ)
        s = S.s()
        m = S.m()
        generators = {}
        for t in StandardTableaux(mu):
            p = self.higher_specht(t, harmonic=True, use_antisymmetry=use_antisymmetry)
            d = self._grading_set([p.degree()]+[0]*(r-1))
            generators.setdefault(d, [])
            generators[d].append(p)
        if use_antisymmetry:
            # FIXME: duplicated logic for computing the
            # antisymmetrization positions, here and in apply_young_idempotent
            antisymmetries = antisymmetries_of_tableau(mu.initial_tableau())
        else:
            antisymmetries = None
        if use_lie:
            use_symmetry=True
            def hilbert_parent(dimensions):
                return s.sum_of_terms([Partition(d), c]
                                       for d,c in dimensions.iteritems() if c)
        elif use_symmetry:
            def hilbert_parent(dimensions):
                return s(m.sum_of_terms([Partition(d), c]
                                         for d,c in dimensions.iteritems())
                        ).restrict_partition_lengths(r, exact=False)
        else:
            def hilbert_parent(dimensions):
                return s(S.from_polynomial(self._hilbert_parent(dimensions))
                        ).restrict_partition_lengths(r,exact=False)

        operators = self.polarization_operators_by_degree(side='down',
                                                          use_symmetry=use_symmetry,
                                                          antisymmetries=antisymmetries,
                                                          min_degree=1 if use_lie else 0)
        if use_lie:
            operators[self._grading_set.zero()] = [
                functools.partial(lambda v,i: self.polarization(self.polarization(v, i+1,i, 1,antisymmetries=antisymmetries), i,i+1, 1,antisymmetries=antisymmetries), i=i)
                for i in range(r-1)
                ]
        # print operators
        add_degree = self._add_degree_symmetric if use_symmetry else self._add_degree
        F = Subspace(generators, operators=operators, add_degrees=add_degree, verbose=verbose)
        F._hilbert_parent = hilbert_parent
        F.antisymmetries = antisymmetries
        return F


    def harmonic_character(self, mu, verbose=False, use_symmetry=False, use_antisymmetry=False, use_lie=False):
        """
        Return the `GL_r` character of the space of diagonally harmonic polynomials
        contributed by a given `S_n` irreducible representation.

        EXAMPLES::

            sage: P = DiagonalPolynomialRing(QQ,3,2)
            sage: P.harmonic_character(Partition([3,2]))
            s[] # s[3] + s[1] # s[2, 1] + s[1, 1] # s[1, 1, 1] + s[2] # s[2, 1] + s[3] # s[1, 1, 1]

        """
        mu = Partition(mu)
        F = self.harmonic_space_by_shape(mu, verbose=verbose,
                                         use_symmetry=use_symmetry,
                                         use_antisymmetry=use_antisymmetry,
                                         use_lie=use_lie)
        F.finalize()
        if not use_lie:
            return F.hilbert_polynomial()
        operators = [functools.partial(self.polarization, i1=i1, i2=i2, d=1,
                                       antisymmetries=F.antisymmetries)
                     for i1 in range(1, self._r)
                     for i2 in range(i1)]
        return F._hilbert_parent({mu: len(annihilator_basis(basis._basis, operators, action=lambda b, op: op(b), ambient=self))
                                  for mu, basis in F._bases.iteritems() if basis._basis})

    def harmonic_bicharacter(self, verbose=False, use_symmetry=False, use_antisymmetry=False, use_lie=False):
        """
        Return the `GL_r-S_n` character of the space of diagonally harmonic polynomials

        EXAMPLES::

            sage: P = DiagonalPolynomialRing(QQ,3,2)
            sage: P.harmonic_bicharacter()
            s[] # s[3] + s[1] # s[2, 1] + s[1, 1] # s[1, 1, 1] + s[2] # s[2, 1] + s[3] # s[1, 1, 1]

        """
        s = SymmetricFunctions(ZZ).s()
        def char(mu):
            if verbose:
                print "%s:"%s(mu)
            r = tensor([self.harmonic_space_by_shape(mu, verbose=verbose,
                                                     use_symmetry=use_symmetry,
                                                     use_antisymmetry=use_antisymmetry,
                                                     use_lie=use_lie,
                                                    ).hilbert_polynomial(),
                        s[mu]])
            return r
        # TODO Understand why this does not work in parallel
        #char = parallel()(char)
        #return sum( res[1] for res in char(Partitions(self._n).list()) )
        return sum(char(mu) for mu in Partitions(self._n))

def harmonic_character_plain(mu):
    mu = Partition(mu)
    n = mu.size()
    print mu
    if len(mu) == n:
        r = n-1
    else:
        r = n-2
    r = max(r, 1)
    R = DiagonalPolynomialRing(QQ, n, r)
    result = R.harmonic_character(mu, verbose=False,
                                  use_symmetry=True,
                                  use_lie=True,
                                  use_antisymmetry=True)
    return {tuple(degrees): dim
            for degrees, dim in result}

harmonic_character_plain = func_persist(harmonic_character_plain,
                                        hash=lambda mu: str(list(mu)).replace(" ","")[1:-1],
                                        key=lambda mu: tuple(Partition(mu))
                                        )

"""
Migrating persistent database from previous format::

    sage: SymmetricFunctions(ZZ).inject_shorthands()
    sage: myhash=lambda mu: str(list(mu)).replace(" ","")[1:-1]
    sage: cd func_persist                                        # not tested
    sage: for filename in glob.glob("harmonic_character*.sobj"): # not tested
    ....:     obj = load(filename)
    ....:     key = obj[0][0][0]
    ....:     value = obj[1]
    ....:     chi = s(m.sum_of_terms([Partition(nu), c] for nu, c in value.iteritems())).restrict_partition_lengths(max(4, len(key)-1), exact=False)
    ....:     print key, chi
    ....:     value = {tuple(nu):c for nu,c in chi }
    ....:     save((key,value), "plain/harmonic_character_plain_%s"%(myhash(key)))

Inserting François's value for the character for `1^6` in the database::

    sage: S = SymmetricFunctions(ZZ)
    sage: s = S.s()
    sage: res = s[1, 1, 1, 1, 1] + s[3, 1, 1, 1] + s[4, 1, 1, 1] + s[4, 2, 1] + s[4, 3, 1] + s[4, 4] + s[4, 4, 1] + s[5, 1, 1, 1] + s[5, 2, 1] + s[5, 3, 1] + s[6, 1, 1] + s[6,1, 1, 1] + s[6, 2, 1] + s[6, 3] + s[6, 3, 1] + s[6, 4] + s[7, 1, 1] + s[7, 2] +s[7, 2, 1] + s[7, 3] + s[7, 4] + 2*s[8, 1, 1] + s[8, 2] + s[8, 2, 1] + s[8, 3] + s[9, 1, 1] + s[9, 2] + s[9, 3] + s[10, 1] + s[10, 1, 1] + s[10, 2] + s[11, 1] + s[11, 2] + s[12, 1] + s[13, 1] + s[15]
    sage: key=tuple([1,1,1,1,1,1])
    sage: value = {tuple(mu):c for mu,c in res}
    sage: myhash=lambda mu: str(list(mu)).replace(" ","")[1:-1]
    sage: save((key,value), "func_persist/harmonic_character_plain_%s"%(myhash(key))) # not tested
"""

def harmonic_character(mu):
    """
    Return the contribution of an `S_n` isotypic component in the
    diagonal harmonic polynomials

    Let `H` be the space of diagonal harmonic harmonic polynomials on
    `k\times n` variables, with `k` large enough.  Write its `GL_k
    \times S_n` bicharacter as `\sum f_\mu \otimes s_\mu`.  This
    computes `f_\mu`.

    EXAMPLES::

        sage: harmonic_character([6])
        s[]
        sage: harmonic_character([5, 1])
        s[1] + s[2] + s[3] + s[4] + s[5]
        sage: harmonic_character([4, 2])
        s[2] + s[2, 1] + s[2, 2] + s[3] + s[3, 1] + s[3, 2] + 2*s[4] + 2*s[4, 1] + s[4, 2] + s[5] + s[5, 1] + 2*s[6] + s[6, 1] + s[7] + s[8]
        sage: harmonic_character([4, 1, 1])
        s[1, 1] + s[2, 1] + s[3] + 2*s[3, 1] + s[3, 2] + s[3, 3] + s[4] + 2*s[4, 1] + s[4, 2] + 2*s[5] + 2*s[5, 1] + s[5, 2] + 2*s[6] + s[6, 1] + 2*s[7] + s[7, 1] + s[8] + s[9]
        sage: harmonic_character([3, 3])
        s[2, 2] + s[2, 2, 1] + s[3] + s[3, 1] + s[3, 2] + s[4, 1] + s[4, 1, 1] + s[4, 2] + s[5] + s[5, 1] + s[5, 2] + s[6] + s[6, 1] + s[7] + s[7, 1] + s[9]
        sage: harmonic_character([2, 2, 2])
        s[2, 2] + s[2, 2, 1] + s[3, 1, 1] + s[3, 1, 1, 1] + s[3, 2, 1] + s[3, 3, 1] + s[4, 1] + s[4, 1, 1] + 2*s[4, 2] + s[4, 2, 1] + s[4, 3] + s[4, 4] + s[5, 1] + 2*s[5, 1, 1] + 2*s[5, 2] + s[5, 2, 1] + s[5, 3] + s[6] + 2*s[6, 1] + s[6, 1, 1] + 2*s[6, 2] + s[6, 3] + 2*s[7, 1] + s[7, 1, 1] + s[7, 2] + s[8] + 2*s[8, 1] + s[8, 2] + s[9] + s[9, 1] + s[10] + s[10, 1] + s[12]
        sage: harmonic_character([3, 1, 1, 1])
        s[1, 1, 1] + s[2, 1, 1] + s[3, 1] + 2*s[3, 1, 1] + s[3, 2] + s[3, 2, 1] + 2*s[3, 3] + s[3, 3, 1] + 2*s[4, 1] + 2*s[4, 1, 1] + 2*s[4, 2] + s[4, 2, 1] + 2*s[4, 3] + 3*s[5, 1] + 2*s[5, 1, 1] + 3*s[5, 2] + s[5, 2, 1] + 2*s[5, 3] + s[6] + 4*s[6, 1] + s[6, 1, 1] + 3*s[6, 2] + s[6, 3] + s[7] + 4*s[7, 1] + s[7, 1, 1] + 2*s[7, 2] + 2*s[8] + 3*s[8, 1] + s[8, 2] + 2*s[9] + 2*s[9, 1] + 2*s[10] + s[10, 1] + s[11] + s[12]
        sage: harmonic_character([3, 2, 1])
        s[2, 1] + s[2, 1, 1] + s[2, 2] + s[2, 2, 1] + 2*s[3, 1] + 2*s[3, 1, 1] + 3*s[3, 2] + 2*s[3, 2, 1] + s[3, 3] + s[4] + 3*s[4, 1] + 2*s[4, 1, 1] + 4*s[4, 2] + s[4, 2, 1] + 2*s[4, 3] + 2*s[5] + 5*s[5, 1] + 2*s[5, 1, 1] + 4*s[5, 2] + s[5, 3] + 2*s[6] + 5*s[6, 1] + s[6, 1, 1] + 3*s[6, 2] + 3*s[7] + 4*s[7, 1] + s[7, 2] + 3*s[8] + 3*s[8, 1] + 2*s[9] + s[9, 1] + 2*s[10] + s[11]
        sage: harmonic_character([2, 1, 1, 1, 1])
        s[1, 1, 1, 1] + s[2, 1, 1, 1] + s[3, 1, 1] + s[3, 1, 1, 1] + s[3, 2, 1] + s[3, 3, 1] + 2*s[4, 1, 1] + s[4, 1, 1, 1] + s[4, 2] + 2*s[4, 2, 1] + 2*s[4, 3] + 2*s[4, 3, 1] + s[4, 4] + 3*s[5, 1, 1] + s[5, 1, 1, 1] + s[5, 2] + 2*s[5, 2, 1] + 2*s[5, 3] + s[5, 3, 1] + s[5, 4] + s[6, 1] + 3*s[6, 1, 1] + 3*s[6, 2] + 2*s[6, 2, 1] + 3*s[6, 3] + s[6, 4] + 2*s[7, 1] + 3*s[7, 1, 1] + 3*s[7, 2] + s[7, 2, 1] + 2*s[7, 3] + 3*s[8, 1] + 2*s[8, 1, 1] + 3*s[8, 2] + s[8, 3] + 3*s[9, 1] + s[9, 1, 1] + 2*s[9, 2] + s[10] + 3*s[10, 1] + s[10, 2] + s[11] + 2*s[11, 1] + s[12] + s[12, 1] + s[13] + s[14]
        sage: harmonic_character([2, 2, 1, 1])
        s[2, 1, 1] + s[2, 1, 1, 1] + s[2, 2, 1] + s[3, 1, 1] + s[3, 1, 1, 1] + s[3, 2] + 2*s[3, 2, 1] + s[3, 3] + s[3, 3, 1] + s[4, 1] + 3*s[4, 1, 1] + s[4, 1, 1, 1] + 2*s[4, 2] + 3*s[4, 2, 1] + 2*s[4, 3] + s[4, 3, 1] + s[4, 4] + 2*s[5, 1] + 3*s[5, 1, 1] + 4*s[5, 2] + 2*s[5, 2, 1] + 3*s[5, 3] + s[5, 4] + 3*s[6, 1] + 4*s[6, 1, 1] + 4*s[6, 2] + s[6, 2, 1] + 2*s[6, 3] + s[7] + 4*s[7, 1] + 2*s[7, 1, 1] + 4*s[7, 2] + s[7, 3] + s[8] + 4*s[8, 1] + s[8, 1, 1] + 2*s[8, 2] + 2*s[9] + 4*s[9, 1] + s[9, 2] + s[10] + 2*s[10, 1] + 2*s[11] + s[11, 1] + s[12] + s[13]
        sage: harmonic_character([1, 1, 1, 1, 1, 1])
        s[1, 1, 1, 1, 1] + s[3, 1, 1, 1] + s[4, 1, 1, 1] + s[4, 2, 1] + s[4, 3, 1] + s[4, 4] + s[4, 4, 1] + s[5, 1, 1, 1] + s[5, 2, 1] + s[5, 3, 1] + s[6, 1, 1] + s[6, 1, 1, 1] + s[6, 2, 1] + s[6, 3] + s[6, 3, 1] + s[6, 4] + s[7, 1, 1] + s[7, 2] + s[7, 2, 1] + s[7, 3] + s[7, 4] + 2*s[8, 1, 1] + s[8, 2] + s[8, 2, 1] + s[8, 3] + s[9, 1, 1] + s[9, 2] + s[9, 3] + s[10, 1] + s[10, 1, 1] + s[10, 2] + s[11, 1] + s[11, 2] + s[12, 1] + s[13, 1] + s[15]
        """
    mu = tuple(mu)
    result = harmonic_character_plain(mu)
    S = SymmetricFunctions(ZZ)
    s = S.s()
    return s.sum_of_terms([Partition(d), c] for d,c in result.iteritems())

@parallel()
def harmonic_character_paral(mu):
    t1 = datetime.datetime.now()
    result = harmonic_character_plain(mu)
    t2 = datetime.datetime.now()
    return result, t2-t1

def harmonic_characters(n):
    """
    Compute in parallel the harmonic characters for all
    irreducible representations of `S_n`.
    """
    S = SymmetricFunctions(ZZ)
    s = S.s()
    for (((nu,),_), (result, t)) in harmonic_character_paral((tuple(mu),) for mu in Partitions(n)):
        print Partition(nu), "\t("+str(t)[:-7]+"):",s.sum_of_terms([Partition(d), c]
                                                                   for d,c in result.iteritems())

def harmonic_bicharacter_truncated_series():
    """
    Return the diagonal harmonic bicharacter series, truncated to
    whatever has already been computed and stored in the database.

    OUTPUT: a sum `\sum c_{\lambda,\mu} s_\lambda \tensor s_\mu`

    EXAMPLES::

        sage: Harm = harmonic_bicharacter_truncated_series()

        sage: SymmetricFunctions(ZZ).inject_shorthands()
        sage: s.sum_of_terms([nu,c] for ((mu,nu),c) in Harm if mu == [1,1])

        sage: H = sum(h[i] for i in range(0, 10))

        sage: H
        h[] + h[1] + h[2] + h[3] + h[4] + h[5] + h[6] + h[7] + h[8] + h[9]
        sage: Hinv = s(1-e[1]+e[2]-e[3]+e[4]-e[5]+e[6])

        sage: truncate(H*Hinv,6)
        h[]


        sage: bitruncate(Harm * tensor([s.one(), (1-s[1]+s[2]-s[3]+s[4]-s[5])]), 6)

    Not quite::

        sage: bitruncate(Harm * tensor([s.one(), Hinv]), 6)
        s[] # s[] + s[1] # s[1, 1] - s[1] # s[1, 1, 1] + s[1] # s[1, 1, 1, 1] - s[1] # s[1, 1, 1, 1, 1] + s[1, 1] # s[1, 1, 1] - s[1, 1] # s[1, 1, 1, 1] + s[1, 1] # s[1, 1, 1, 1, 1] + s[1, 1, 1] # s[1, 1, 1, 1] - s[1, 1, 1] # s[1, 1, 1, 1, 1] + s[1, 1, 1, 1] # s[1, 1, 1, 1, 1] + s[2] # s[2, 1] - s[2] # s[2, 1, 1] + s[2] # s[2, 1, 1, 1] + s[2, 1] # s[2, 1, 1] - s[2, 1] # s[2, 1, 1, 1] + s[2, 1] # s[2, 2] - s[2, 1] # s[2, 2, 1] + s[2, 1, 1] # s[2, 1, 1, 1] + s[2, 1, 1] # s[2, 2, 1] + s[2, 2] # s[2, 2, 1] + s[2, 2] # s[3, 2] + s[3] # s[1, 1, 1] - s[3] # s[1, 1, 1, 1] + s[3] # s[1, 1, 1, 1, 1] + s[3] # s[3, 1] - s[3] # s[3, 1, 1] + s[3, 1] # s[1, 1, 1, 1] - s[3, 1] # s[1, 1, 1, 1, 1] + s[3, 1] # s[2, 1, 1] - s[3, 1] # s[2, 1, 1, 1] + s[3, 1] # s[3, 1, 1] + s[3, 1] # s[3, 2] + s[3, 1, 1] # s[1, 1, 1, 1, 1] + s[3, 1, 1] # s[2, 1, 1, 1] + s[3, 1, 1] # s[2, 2, 1] + s[3, 2] # s[2, 1, 1, 1] + s[3, 2] # s[2, 2, 1] + s[3, 2] # s[3, 1, 1] + s[4] # s[2, 1, 1] - s[4] # s[2, 1, 1, 1] + s[4] # s[2, 2] - s[4] # s[2, 2, 1] + s[4] # s[4, 1] + s[4, 1] # s[1, 1, 1, 1] - s[4, 1] # s[1, 1, 1, 1, 1] + s[4, 1] # s[2, 1, 1, 1] + 2*s[4, 1] # s[2, 2, 1] + s[4, 1] # s[3, 1, 1] + s[4, 1] # s[3, 2] + s[5] # s[2, 1, 1] - s[5] # s[2, 1, 1, 1] + s[5] # s[3, 1, 1] + s[5] # s[3, 2]
    """
    s = SymmetricFunctions(ZZ).s()
    ss = tensor([s,s])
    return ss.sum_of_terms([(Partition(mu), Partition(nu)), c]
                           for nu,d in harmonic_character_plain.dict().iteritems()
                           for mu,c in d.iteritems())

def truncate(f,d):
    return f.map_support_skip_none(lambda mu: mu if mu.size() < d else None)

def bitruncate(f,d):
    return f.map_support_skip_none(lambda (mu,nu): (mu,nu) if mu.size() < d and nu.size() < d else None)

##############################################################################
# Polynomials as differential operators
##############################################################################

def polynomial_derivative_on_basis(e, f):
    """
    Return the differentiation of `f` by `e`.

    INPUT:

    - `e`, `f` -- exponent vectors representing two monomials `X^e` and `X^f`
                  (type: :class:`sage.rings.polynomial.polydict.ETuple`)

    OUTPUT:

    - a pair `(g,c)` where `g` is an exponent vector and `c` a
      coefficient, representing the term `c X^g`, or :obj:`None` if
      the result is zero.

    Let `R=K[X]` be a multivariate polynomial ring. Write `X^e` for
    the monomial with exponent vector `e`, and `p(\partial)` the
    differential operator obtained by substituting each variable `x`
    in `p` by `\frac{\partial}{\partial x}`.

    This returns `X^e(\partial)(X^f)`

    EXAMPLES::

        sage: from sage.rings.polynomial.polydict import ETuple
        sage: polynomial_derivative_on_basis(ETuple((4,0)), ETuple((4,0)))
        ((0, 0), 24)
        sage: polynomial_derivative_on_basis(ETuple((0,3)), ETuple((0,3)))
        ((0, 0), 6)
        sage: polynomial_derivative_on_basis(ETuple((0,1)), ETuple((0,3)))
        ((0, 2), 3)
        sage: polynomial_derivative_on_basis(ETuple((2,0)), ETuple((4,0)))
        ((2, 0), 12)
        sage: polynomial_derivative_on_basis(ETuple((2,1)), ETuple((4,3)))
        ((2, 2), 36)
        sage: polynomial_derivative_on_basis(ETuple((1,3)), ETuple((1,2)))
        sage: polynomial_derivative_on_basis(ETuple((2,0)), ETuple((1,2)))
    """
    g = f.esub(e)
    if any(i < 0 for i in g):
        return None
    return (g, prod(factorial(i)/factorial(j) for (i,j) in zip(f,g)))

def polynomial_derivative(p, q): # this just extends a function by bilinearity; we would want it to be built using ModulesWithBasis
    """
    Return the derivative of `q` w.r.t. `p`.

    INPUT:

    - `p`, `q` -- two polynomials in the same multivariate polynomial ring `\K[X]`

    OUTPUT: a polynomial

    The polynomial `p(\partial)(q)`, where `p(\partial)` the
    differential operator obtained by substituting each variable `x`
    in `p` by `\frac{\partial}{\partial x}`.

    EXAMPLES::

        sage: R = QQ['x,y']
        sage: x,y = R.gens()

        sage: polynomial_derivative(x, x)
        1
        sage: polynomial_derivative(x, x^3)
        3*x^2
        sage: polynomial_derivative(x^2, x^3)
        6*x
        sage: polynomial_derivative(x+y, x^3)
        3*x^2
        sage: polynomial_derivative(x+y, x^3*y^3)
        3*x^3*y^2 + 3*x^2*y^3

        sage: p = -x^2*y + 3*y^2
        sage: q = x*(x+2*y+1)^3

        sage: polynomial_derivative(p, q)
        72*x^2 + 144*x*y + 36*x - 48*y - 24
        sage: -diff(q, [x,x,y]) + 3 * diff(q, [y,y])
        72*x^2 + 144*x*y + 36*x - 48*y - 24
    """
    if not have_same_parent(p,q):
        raise ValueError("p and q should have the same parent")
    R = p.parent()
    result = R.zero() # We would want to use R.sum_of_terms_if_not_None
    for (e1, c1) in items_of_vector(p):
        for (e2, c2) in items_of_vector(q):
            m = polynomial_derivative_on_basis(e1,e2)
            if m is None:
                continue
            (e3,c3) = m
            result += R({e3: c1*c2*c3})
    return result
