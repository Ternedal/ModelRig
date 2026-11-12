package httpapi

import (
 "encoding/json"
 "strings"
 "testing"
)

func TestDecodeUniqueJSONRejectsDuplicateKeys(t *testing.T) {
 for _,input:=range []string{
  `{"id":"one","id":"two"}`,
  `[{"id":"one","nested":{"x":1,"x":2}}]`,
  `[1,2,`,
 } {
  dec:=json.NewDecoder(strings.NewReader(input))
  if _,err:=decodeUniqueJSON(dec);err==nil {t.Errorf("accepted invalid JSON: %s",input)}
 }
}

func TestDecodeUniqueJSONAcceptsProducerIndex(t *testing.T) {
 input:=`[{"id":"asset_1","kind":"image","mime_type":"image/png","size_bytes":4,"created_at":"2026-11-11T10:00:00Z"}]`
 dec:=json.NewDecoder(strings.NewReader(input))
 value,err:=decodeUniqueJSON(dec)
 if err!=nil {t.Fatal(err)}
 entries,ok:=value.([]any)
 if !ok || len(entries)!=1 {t.Fatalf("unexpected decoded entries: %#v",value)}
}

func TestLocalMediaCatalogRefusesUnconfiguredAndSystemVolume(t *testing.T) {
 for _,c:=range []LocalMediaCatalog{
  {},
  {VolumeRoot:"/",MediaRoot:"/tmp"},
  {VolumeRoot:"relative/path",MediaRoot:"relative/path/media"},
 } {
  if _,err:=c.root();err==nil {t.Errorf("accepted unsafe root: %+v",c)}
 }
}

func TestLocalMediaCatalogRefusesOtherOwner(t *testing.T) {
 c:=LocalMediaCatalog{}
 if _,_,err:=c.ListMedia("other",50,"");err==nil {t.Fatal("cross-owner listing accepted")}
 if file,_,_,err:=c.OpenMedia("other","asset_1");err==nil || file!=nil {t.Fatal("cross-owner asset accepted")}
}

func TestDecodeUniqueJSONRejectsOversizedArray(t *testing.T) {
 // The decoder must stop before materialising an unbounded index.
 input := "[" + strings.Repeat("0,", 10000) + "0]"
 dec := json.NewDecoder(strings.NewReader(input))
 if _, err := decodeUniqueJSON(dec); err == nil {
  t.Fatal("accepted index with more than 10000 entries")
 }
}

func TestDecodeUniqueJSONRejectsDuplicateEscapedKey(t *testing.T) {
 // JSON object keys must be compared after unescaping.
 dec := json.NewDecoder(strings.NewReader(`{"id":1,"\\u0069d":2}`))
 if _, err := decodeUniqueJSON(dec); err == nil {
  t.Fatal("accepted semantically duplicate JSON keys")
 }
}
