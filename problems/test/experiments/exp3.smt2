;; (param (A B C D) polygon)
(param A point)
(param B point)
(param C point)
(param D point)
(assert (coll A B C))
(assert (coll B C D))
(eval (coll A B C))