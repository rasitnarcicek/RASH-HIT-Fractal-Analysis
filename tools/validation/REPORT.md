# RASH-HIT v1.3.0 Bilimsel Dogrulama Protorolu

- Tarih: 2026-10-21
- Sonuc: **PASS**
- Kavramsal zincir: kesik teori (exact counts) -> bagimsiz oracle birebir eslesme -> bagimsiz Pillow raster teyidi -> pencerelestirilmis Db teori yaklasimi.

```
====================================================================================================
RASH-HIT SCIENTIFIC VALIDATION  (engine v1.3.0, levels=7)
====================================================================================================

1) square_full.svg [area] -- N(L)=16*4^(L-1) EXACT -> Db=2.000000
   counts      : [16, 64, 256, 1024, 4096, 16384, 65536]
   expected    : [16, 64, 256, 1024, 4096, 16384, 65536]
   counts exact: True   Db: 2.0 (err 0.00e+00)  R2: 1.0

2) horizontal_line.svg [supercover] -- N(L) tam olarak 2x katlanir -> Db=1.000000
   counts        : [8, 16, 32, 64, 128, 256, 512]
   doubling exact: True  Db: 1.0 (err 0.00e+00)  R2: 1.0

3) carpet.svg [area] -- TEORI: Db = log(8)/log(3) = 1.8927893
   counts       : [16, 60, 236, 864, 3312, 12172, 45812]
   tam-sayi oracle: [16, 60, 236, 864, 3312, 12172, 45812]
   ENGINE == ORACLE (birebir): True
   Db (best window L3-L7): 1.901798 (R2 0.999977, err 0.0090)
   PASS tolerance (|err|<0.03): True

4) gasket.svg [supercover] -- TEORI: Db = log(3)/log(2) = 1.5849625
   counts       : [13, 43, 141, 451, 1413, 4363, 13341]
   GEOS oracle  : [13, 43, 141, 451, 1413, 4363, 13341]
   ENGINE == ORACLE (birebir): True
   Db (best window L4-L7): 1.628635 (R2 0.999977, err 0.0437)
   (legacy full-range Db engine raporu: 1.666575 -- backward-compat surumu)
   PASS tolerance (|err|<0.06): True

5) carpet -- Pillow bagimsiz raster + saf NumPy bitmap sayim
   bitmap Db: 1.909979 (R2 0.999954)
   engine windowed Db: 1.901798  fark: 0.0082

====================================================================================================
OVERALL SCIENTIFIC VALIDATION: PASS
```
