package httpapi

import (
 "encoding/json"
 "errors"
 "io"
 "os"
 "path/filepath"
 "runtime"
 "strings"
 "time"
)

// LocalMediaCatalog reads the producer's published index on an explicitly
// configured external volume. No client-provided filesystem path is accepted.
// The operator must supply the volume root and the media directory.
type LocalMediaCatalog struct { VolumeRoot, MediaRoot string }

type localMediaEntry struct {
 ID string `json:"id"`
 Kind string `json:"kind"`
 MIME string `json:"mime_type"`
 Size int64 `json:"size_bytes"`
 CreatedAt string `json:"created_at"`
}

func (c LocalMediaCatalog) root() (string,error) {
 if c.VolumeRoot=="" || c.MediaRoot=="" { return "",ErrMediaUnavailable }
 volume,err:=filepath.Abs(c.VolumeRoot);if err!=nil{return "",ErrMediaUnavailable}
 media,err:=filepath.Abs(c.MediaRoot);if err!=nil{return "",ErrMediaUnavailable}
 // The volume must be a filesystem root, never an ordinary fallback folder.
 if filepath.Clean(volume)!=filepath.Clean(filepath.VolumeName(volume)+string(os.PathSeparator)) {return "",ErrMediaUnavailable}
 // The production media volume is Z: on Windows. Never read C: or another
 // unapproved drive when an operator accidentally supplies the wrong root.
 if runtime.GOOS=="windows" && !strings.EqualFold(filepath.VolumeName(volume),"Z:") {return "",ErrMediaUnavailable}
 // POSIX '/' is the system disk, not an external media mount.
 if runtime.GOOS!="windows" {return "",ErrMediaUnavailable}
 for _,path:=range []string{volume,media} {
  info,err:=os.Lstat(path);if err!=nil || !info.IsDir() || info.Mode()&os.ModeSymlink!=0{return "",ErrMediaUnavailable}
  resolved,err:=filepath.EvalSymlinks(path);if err!=nil || filepath.Clean(resolved)!=filepath.Clean(path){return "",ErrMediaUnavailable}
 }
 rel,err:=filepath.Rel(volume,media)
 if err!=nil || rel=="." || rel==".." || filepath.IsAbs(rel) || strings.HasPrefix(rel,".."+string(os.PathSeparator)){return "",ErrMediaUnavailable}
 return media,nil
}

func (c LocalMediaCatalog) entries() ([]localMediaEntry,error) {
 root,err:=c.root();if err!=nil{return nil,err}
 path:=filepath.Join(root,"gallery-index.json")
 info,err:=os.Lstat(path);if err!=nil || !info.Mode().IsRegular() || info.Size()>4*1024*1024{return nil,ErrMediaUnavailable}
 f,err:=os.Open(path);if err!=nil{return nil,ErrMediaUnavailable};defer f.Close()
 info,err=f.Stat();if err!=nil || !info.Mode().IsRegular() || info.Size()>4*1024*1024{return nil,ErrMediaUnavailable}
 dec:=json.NewDecoder(io.LimitReader(f,4*1024*1024+1))
 var rows []localMediaEntry
 raw,err:=decodeUniqueJSON(dec)
 if err!=nil{return nil,ErrMediaUnavailable}
 if !errors.Is(dec.Decode(new(any)),io.EOF){return nil,ErrMediaUnavailable}
 array,ok:=raw.([]any);if !ok{return nil,ErrMediaUnavailable}
 for _,value:=range array {
  entry,ok:=value.(map[string]any);if !ok{return nil,ErrMediaUnavailable}
  // Reject producer-controlled locations and unrecognised metadata rather
  // than silently ignoring values that may become trusted in a later version.
  allowed:=map[string]bool{"id":true,"kind":true,"mime_type":true,"size_bytes":true,"created_at":true}
  for key:=range entry {if !allowed[key]{return nil,ErrMediaUnavailable}}
 }
 payload,err:=json.Marshal(raw);if err!=nil{return nil,ErrMediaUnavailable}
 if err:=json.Unmarshal(payload,&rows);err!=nil || len(rows)>10000{return nil,ErrMediaUnavailable}
 seen:=map[string]bool{}
 for _,e:=range rows {
  if !validMediaID(e.ID)||seen[e.ID]||e.Size<=0||e.CreatedAt==""{return nil,ErrMediaUnavailable}
  parsed,err:=time.Parse(time.RFC3339Nano,e.CreatedAt);if err!=nil || !strings.HasSuffix(e.CreatedAt,"Z") || parsed.Location()!=time.UTC{return nil,ErrMediaUnavailable}
  seen[e.ID]=true
  if (e.Kind=="video" && e.MIME!="video/mp4") || (e.Kind=="image" && e.MIME!="image/png" && e.MIME!="image/jpeg" && e.MIME!="image/webp") || (e.Kind!="image" && e.Kind!="video"){return nil,ErrMediaUnavailable}
 }
 return rows,nil
}

func (c LocalMediaCatalog) ListMedia(owner string,limit int,cursor string)([]map[string]any,*string,error){
 if owner!=mediaInstallationOwner || limit<1 || limit>100{return nil,nil,ErrMediaUnavailable}
 rows,err:=c.entries();if err!=nil{return nil,nil,err}
 start:=0
 if cursor!="" {
  found:=false
  for i,e:=range rows {if e.ID==cursor{start=i+1;found=true;break}}
  if !found{return nil,nil,ErrMediaUnavailable}
 }
 end:=start+limit;if end>len(rows){end=len(rows)}
 out:=make([]map[string]any,0,end-start)
 for _,e:=range rows[start:end] {
  out=append(out,map[string]any{"id":e.ID,"kind":e.Kind,"mime_type":e.MIME,"size_bytes":e.Size,"created_at":e.CreatedAt,"url":"/api/v1/media/"+e.ID,"playback":map[string]any{"supports_range":e.Kind=="video"}})
 }
 var next *string
 if end<len(rows)&&end>start {id:=rows[end-1].ID;next=&id}
 return out,next,nil
}

func (c LocalMediaCatalog) OpenMedia(owner,id string)(io.ReadSeekCloser,string,int64,error){
 if owner!=mediaInstallationOwner || !validMediaID(id){return nil,"",0,ErrMediaNotFound}
 rows,err:=c.entries();if err!=nil{return nil,"",0,err}
 var entry *localMediaEntry
 for i:=range rows {if rows[i].ID==id{entry=&rows[i];break}}
 if entry==nil{return nil,"",0,ErrMediaNotFound}
 ext:=map[string]string{"video/mp4":".mp4","image/png":".png","image/jpeg":".jpg","image/webp":".webp"}[entry.MIME]
 root,err:=c.root();if err!=nil{return nil,"",0,err}
 path:=filepath.Join(root,id+ext)
 info,err:=os.Lstat(path);if err!=nil||!info.Mode().IsRegular()||info.Size()!=entry.Size{return nil,"",0,ErrMediaUnavailable}
 f,err:=os.Open(path);if err!=nil{return nil,"",0,ErrMediaUnavailable}
 opened,err:=f.Stat()
 if err!=nil||!opened.Mode().IsRegular()||opened.Size()!=entry.Size||!os.SameFile(info,opened){f.Close();return nil,"",0,ErrMediaUnavailable}
 return f,entry.MIME,entry.Size,nil
}

// decodeUniqueJSON rejects duplicate object keys at every depth. Encoding/json's
// ordinary struct decoder silently accepts duplicates, unlike the Python writer.
func decodeUniqueJSON(d *json.Decoder)(any,error){
 token,err:=d.Token();if err!=nil{return nil,err}
 delimiter,ok:=token.(json.Delim)
 if !ok{return token,nil}
 switch delimiter {
 case '{':
  obj:=make(map[string]any)
  for d.More(){
   keyToken,err:=d.Token();if err!=nil{return nil,err}
   key,ok:=keyToken.(string);if !ok{return nil,ErrMediaUnavailable}
   if _,exists:=obj[key];exists{return nil,ErrMediaUnavailable}
   value,err:=decodeUniqueJSON(d);if err!=nil{return nil,err}
   obj[key]=value
  }
  end,err:=d.Token();if err!=nil||end!=json.Delim('}'){return nil,ErrMediaUnavailable}
  return obj,nil
 case '[':
  var items []any
  for d.More(){item,err:=decodeUniqueJSON(d);if err!=nil{return nil,err};items=append(items,item);if len(items)>10000{return nil,ErrMediaUnavailable}}
  end,err:=d.Token();if err!=nil||end!=json.Delim(']'){return nil,ErrMediaUnavailable}
  return items,nil
 default:
  return nil,ErrMediaUnavailable
 }
}
