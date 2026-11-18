"""Non-secret manifest of the actual inference request body, never its text or key."""
import base64,hashlib,json

def manifest(task,request):
    body=json.loads(request.data);parts=[p for item in body.get('input',[]) for p in item.get('content',[])]
    files=[];images=[];texts=[]
    for p in parts:
        if p['type']=='input_file':
            raw=base64.b64decode(p['file_data'].split(',',1)[1]);files.append({'filename':p.get('filename'),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'format':'PDF' if raw.startswith(b'%PDF') else 'file'})
        elif p['type']=='input_image':
            raw=base64.b64decode(p['image_url'].split(',',1)[1]);images.append({'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'detail':p.get('detail')})
        elif p['type']=='input_text':texts.append({'sha256':hashlib.sha256(p['text'].encode()).hexdigest(),'bytes':len(p['text'].encode())})
    return {'recording':'inference_request_boundary','request_attempted':False,'task':task,'body_sha256':hashlib.sha256(request.data).hexdigest(),'files':files,'images':images,'image_count':len(images),'texts':texts,'html_text':texts[1] if task in ('independent_verify','technical_analysis') and len(texts)>1 else None,'model':body['model'],'max_output_tokens':body['max_output_tokens'],'reasoning_effort':body.get('reasoning',{}).get('effort'),'http_status':None}
