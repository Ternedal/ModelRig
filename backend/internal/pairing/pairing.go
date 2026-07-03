package pairing

import (
	"crypto/rand"
	"math/big"
	"strings"
)

// alphabet excludes visually ambiguous characters: 0/O and 1/I/L.
const alphabet = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

// Code returns an unambiguous pairing code in XXXX-XXXX form (9 chars incl. dash).
//
// Short codes exist because long SHA tokens are unusable to type on a phone.
// This mirrors the BeerRig fix.
func Code() (string, error) {
	const n = 8
	b := make([]byte, n)
	max := big.NewInt(int64(len(alphabet)))
	for i := 0; i < n; i++ {
		idx, err := rand.Int(rand.Reader, max)
		if err != nil {
			return "", err
		}
		b[i] = alphabet[idx.Int64()]
	}
	s := string(b)
	return s[:4] + "-" + s[4:], nil
}

// Normalize canonicalizes user input to XXXX-XXXX. Callers must still validate
// the returned length (9) before use.
func Normalize(in string) string {
	in = strings.ToUpper(strings.TrimSpace(in))
	in = strings.ReplaceAll(in, "-", "")
	in = strings.ReplaceAll(in, " ", "")
	if len(in) != 8 {
		return in
	}
	return in[:4] + "-" + in[4:]
}
