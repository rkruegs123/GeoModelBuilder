(param (A B C) triangle)
(param D point)
(param E point)
(let Gamma circle (incircle (midp A (midp B E)) D C))
(eval (coll A B D))
