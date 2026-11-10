package httpapi

import (
 "bytes"
 "io"
 "net/http"
 "net/http/httptest"
 "strings"
 "testing"
)

type mediaTestCatalog struct {
 data []byte
 listCalls int
 openCalls int
 owner string
}
func (m *mediaTestCatalog) ListMedia(owner string, limit int, cursor string) ([]map[string]any, *string, error) {
 m.listCalls++; m.owner=owner
 return []map[string]any{{"id":"asset_1","kind":"video","mime_type":"video/mp4","url":"/api/v1/media/asset_1"}},nil,nil
}
func (m *mediaTestCatalog) OpenMedia(owner,id string) (io.ReadSeekCloser,string,int64,error) {
 m.openCalls++; m.owner=owner
 if id!="asset_1" { return nil,"",0,ErrMediaNotFound }
 return &mediaTestReadSeekCloser{Reader:bytes.NewReader(m.data)},"video/mp4",int64(len(m.data)),nil
}
type mediaTestReadSeekCloser struct { *bytes.Reader }
func (*mediaTestReadSeekCloser) Close() error { return nil }

func TestMediaHandlersFailClosedWithoutCatalog(t *testing.T) {
 s:=&server{}
 for _,tc:=range []struct{method,path string}{
  {"GET","/api/v1/media"},{"GET","/api/v1/media/asset_1"},{"HEAD","/api/v1/media/asset_1"},
 } {
  w:=httptest.NewRecorder()
  s.handleMediaRequestForTest(w,httptest.NewRequest(tc.method,tc.path,nil))
  if w.Code!=503 { t.Fatalf("%s %s: %d",tc.method,tc.path,w.Code) }
 }
}
func (s *server) handleMediaRequestForTest(w http.ResponseWriter,r *http.Request) {
 if strings.HasSuffix(r.URL.Path,"/media") { s.handleMediaList(w,r);return }
 r.SetPathValue("id",strings.TrimPrefix(r.URL.Path,"/api/v1/media/"))
 s.handleMediaAsset(w,r)
}
func TestMediaListContractAndBadInputs(t *testing.T) {
 m:=&mediaTestCatalog{data:[]byte("0123456789")}
 s:=&server{Deps:Deps{Media:m}}
 for _,tc:=range []struct{path string;want int}{
  {"/api/v1/media",200},{"/api/v1/media?limit=1",200},
  {"/api/v1/media?limit=0",400},{"/api/v1/media?limit=1&limit=2",400},
  {"/api/v1/media?cursor=bad%20cursor",400},
 } {
  w:=httptest.NewRecorder();s.handleMediaList(w,httptest.NewRequest("GET",tc.path,nil))
  if w.Code!=tc.want {t.Errorf("%s: %d",tc.path,w.Code)}
  if tc.want==200 && (!strings.Contains(w.Body.String(),"\"schema\":\"kaliv-media-gallery/v1\"") || !strings.Contains(w.Body.String(),"\"next_cursor\":null")) {t.Errorf("bad gallery envelope: %s",w.Body.String())}
 }
 if m.listCalls!=2 || m.owner!=mediaInstallationOwner {t.Fatalf("untrusted owner or invalid query reached catalog: %+v",m)}
}
func TestMediaAssetRangeAndHead(t *testing.T) {
 m:=&mediaTestCatalog{data:[]byte("0123456789")}
 s:=&server{Deps:Deps{Media:m}}
 for _,tc:=range []struct{method,rangeHeader string;want int;body,contentRange string}{
  {"GET","",200,"0123456789",""},
  {"GET","bytes=2-5",206,"2345","bytes 2-5/10"},
  {"GET","bytes=-3",206,"789","bytes 7-9/10"},
  {"GET","items=0-1",200,"0123456789",""},
  {"GET","bytes=1-2,4-5",200,"0123456789",""},
  {"GET","bytes=10-",416,"","bytes */10"},
  {"HEAD","bytes=2-5",206,"","bytes 2-5/10"},
 } {
  r:=httptest.NewRequest(tc.method,"/api/v1/media/asset_1",nil)
  r.SetPathValue("id","asset_1")
  if tc.rangeHeader!="" {r.Header.Set("Range",tc.rangeHeader)}
  w:=httptest.NewRecorder();s.handleMediaAsset(w,r)
  if w.Code!=tc.want || w.Body.String()!=tc.body || w.Header().Get("Content-Range")!=tc.contentRange {
   t.Errorf("%s %q: status=%d body=%q range=%q",tc.method,tc.rangeHeader,w.Code,w.Body.String(),w.Header().Get("Content-Range"))
  }
 }
 if m.owner!=mediaInstallationOwner {t.Fatal("asset owner not installation-scoped")}
}
func TestMediaAssetMissingAndInvalidID(t *testing.T) {
 m:=&mediaTestCatalog{}
 s:=&server{Deps:Deps{Media:m}}
 for _,id:=range []string{"../secret","missing"} {
  r:=httptest.NewRequest("GET","/api/v1/media/asset_1",nil);r.SetPathValue("id",id)
  w:=httptest.NewRecorder();s.handleMediaAsset(w,r)
  if w.Code!=404 {t.Errorf("%s: %d",id,w.Code)}
 }
 if m.openCalls!=1 {t.Fatal("unsafe ID reached catalog")}
}

func TestMediaAssetIfRangeAndNoStore(t *testing.T) {
 m:=&mediaTestCatalog{data:[]byte("0123456789")}
 s:=&server{Deps:Deps{Media:m}}
 r:=httptest.NewRequest("GET","/api/v1/media/asset_1",nil)
 r.SetPathValue("id","asset_1")
 r.Header.Set("Range","bytes=0-2")
 r.Header.Set("If-Range",`"unmatched-etag"`)
 w:=httptest.NewRecorder()
 s.handleMediaAsset(w,r)
 if w.Code!=200 || w.Body.String()!="0123456789" || w.Header().Get("Content-Range")!="" {
  t.Fatalf("If-Range must ignore Range without matching validator: status=%d body=%q range=%q",w.Code,w.Body.String(),w.Header().Get("Content-Range"))
 }
 if w.Header().Get("Cache-Control")!="private, no-store" {t.Fatal("asset may be cached")}
 list:=httptest.NewRecorder()
 s.handleMediaList(list,httptest.NewRequest("GET","/api/v1/media",nil))
 if list.Header().Get("Cache-Control")!="private, no-store" {t.Fatal("gallery may be cached")}
}

func TestMediaRoutesRequireBearerThroughRealMux(t *testing.T) {
 m:=&mediaTestCatalog{data:[]byte("0123456789")}
 handler:=New(Deps{Media:m})
 for _,tc:=range []struct{method,path string}{
  {"GET","/api/v1/media"},
  {"GET","/api/v1/media/asset_1"},
  {"HEAD","/api/v1/media/asset_1"},
 } {
  r:=httptest.NewRequest(tc.method,tc.path,nil)
  w:=httptest.NewRecorder()
  handler.ServeHTTP(w,r)
  if w.Code!=http.StatusUnauthorized {
   t.Errorf("%s %s: want 401, got %d",tc.method,tc.path,w.Code)
  }
 }
 if m.listCalls!=0 || m.openCalls!=0 {
  t.Fatalf("unauthenticated request reached trusted catalog: list=%d open=%d",m.listCalls,m.openCalls)
 }
}

func TestMediaErrorResponsesNeverCache(t *testing.T) {
 for _,tc:=range []struct{method,path string;catalog MediaCatalog;want int}{
  {"GET","/api/v1/media",nil,503},
  {"GET","/api/v1/media?limit=0",&mediaTestCatalog{},400},
  {"GET","/api/v1/media/asset_1",nil,503},
  {"GET","/api/v1/media/bad.dot",&mediaTestCatalog{},404},
  {"GET","/api/v1/media/missing",&mediaTestCatalog{},404},
  {"GET","/api/v1/media/asset_1",&mediaTestCatalog{data:[]byte("123")},200},
 } {
  s:=&server{Deps:Deps{Media:tc.catalog}}
  w:=httptest.NewRecorder()
  s.handleMediaRequestForTest(w,httptest.NewRequest(tc.method,tc.path,nil))
  if w.Code!=tc.want || w.Header().Get("Cache-Control")!="private, no-store" {
   t.Errorf("%s: status=%d cache=%q",tc.path,w.Code,w.Header().Get("Cache-Control"))
  }
 }
}

type mediaBrokenCatalog struct{}
func (mediaBrokenCatalog) ListMedia(string,int,string)([]map[string]any,*string,error){return nil,nil,ErrMediaUnavailable}
func (mediaBrokenCatalog) OpenMedia(string,string)(io.ReadSeekCloser,string,int64,error){
 return nil,"video/mp4",10,nil
}
func TestMediaNilDescriptorFailsClosed(t *testing.T){
 s:=&server{Deps:Deps{Media:mediaBrokenCatalog{}}}
 r:=httptest.NewRequest("GET","/api/v1/media/asset_1",nil)
 r.SetPathValue("id","asset_1")
 w:=httptest.NewRecorder()
 s.handleMediaAsset(w,r)
 if w.Code!=503 || w.Header().Get("Cache-Control")!="private, no-store" {
  t.Fatalf("nil descriptor: status=%d cache=%q",w.Code,w.Header().Get("Cache-Control"))
 }
}

type mediaSeekFailure struct { closed bool }
func (m *mediaSeekFailure) Read([]byte)(int,error){return 0,io.EOF}
func (m *mediaSeekFailure) Seek(int64,int)(int64,error){return 0,io.ErrUnexpectedEOF}
func (m *mediaSeekFailure) Close()error{m.closed=true;return nil}
type mediaSeekFailureCatalog struct{ asset *mediaSeekFailure }
func (m *mediaSeekFailureCatalog) ListMedia(string,int,string)([]map[string]any,*string,error){return nil,nil,nil}
func (m *mediaSeekFailureCatalog) OpenMedia(string,string)(io.ReadSeekCloser,string,int64,error){return m.asset,"video/mp4",10,nil}
func TestMediaSeekFailureDoesNotPublishStaleRangeHeaders(t *testing.T){
 asset:=&mediaSeekFailure{}
 s:=&server{Deps:Deps{Media:&mediaSeekFailureCatalog{asset:asset}}}
 r:=httptest.NewRequest("GET","/api/v1/media/asset_1",nil)
 r.SetPathValue("id","asset_1")
 r.Header.Set("Range","bytes=2-5")
 w:=httptest.NewRecorder()
 s.handleMediaAsset(w,r)
 if w.Code!=503 || w.Header().Get("Content-Length")!="" || w.Header().Get("Content-Range")!="" {
  t.Fatalf("seek failure leaked range metadata: status=%d length=%q range=%q",w.Code,w.Header().Get("Content-Length"),w.Header().Get("Content-Range"))
 }
 if !asset.closed {t.Fatal("failed asset was not closed")}
}
