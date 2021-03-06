#!/usr/bin/env python
# -*- coding: utf-8 -*-

from sage.categories.cartesian_product import cartesian_product
from sage.rings.integer_ring import ZZ

def add_degree(d1,d2):
    """
    Compute the sum componentwise of d1 and d2 and return a grading set
    with no negative component as result.
    
    INPUT:
        - ``d1``,``d2`` -- lists of integers
    
    EXAMPLES::
        
        sage: D = cartesian_product([ZZ for i in range(3)])
        sage: add_degree(D([3,2,1]), D([-2,0,0]))
        (1, 2, 1)
        sage: add_degree(D([3,2,1]), D([-2,1,4]))
        (1, 3, 5)
        sage: add_degree(D([3,2,1]), D([2,1,1]))
        (5, 3, 2)
        sage: add_degree(D([3,2,1]), D([2,1,-2]))
        Traceback (most recent call last):
        ...
        ValueError: invalid degree
    """
    d = d1 + d2
    if not all(i>=0 for i in d):
        raise ValueError("invalid degree")
    return d

def add_degree_symmetric(d1,d2):
    """
    Compute the sum componentwise of d1 and d2 and return a sorted grading
    set with no negative component as result.
    
    INPUT:
        - ``d1``,``d2`` -- lists of integers
    
    EXAMPLES::
        
        sage: D = cartesian_product([ZZ for i in range(3)])
        sage: add_degree_symmetric(D([3,2,1]), D([-2,0,0]))
        (2, 1, 1)
        sage: add_degree_symmetric(D([3,2,1]), D([-2,1,4]))
        (5, 3, 1)
        sage: add_degree_symmetric(D([3,2,1]), D([2,1,1]))
        (5, 3, 2)
        sage: add_degree_symmetric(D([3,2,1]), D([2,1,-2]))
        Traceback (most recent call last):
        ...
        ValueError: invalid degree
    """
    d = d1 + d2
    D = cartesian_product([ZZ for i in range(len(d))])
    if not all(i>=0 for i in d):
        raise ValueError("invalid degree")
    return D(sorted(d, reverse=True))

def add_degree_isotyp(d1,d2):
    """
    Compute the sum componentwise of the lists of integrers contained in d1 and d2 
    and return a grading set and the partition contained in d2 as result.
    
    INPUT:
        - ``d1``,``d2`` -- lists containing a list of integers and a partition

    EXAMPLES::
    
        sage: D = cartesian_product([ZZ for i in range(2)])
        sage: d1 = (D((3,0)),[2,1])
        sage: d2 = (D((-1,0)),[3])
        sage: add_degree_isotyp(d1,d2)
        ((2, 0), [3])

    """
    return d1[0]+d2[0], d2[1]
