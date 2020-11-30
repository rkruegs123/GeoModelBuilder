(param (A B C) triangle)
(let R point (inter-lc (i-bisector B C A) (circumcircle A B C) (rs-neq C)))
(let P point (inter-ll (i-bisector B C A) (perp-bis B C)))
(let Q point (inter-ll (i-bisector B C A) (perp-bis A C)))
(let K point (midp B C))
(let L point (midp A C))
(eval (= (area R P K) (area R Q L)))