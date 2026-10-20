// Pixel-only separation. Native distances and radial world positions never change.
// The GPU uses the same ray/sphere predicate and eight-step bound search.
export function boundedBallOffset(raw, offset, viewport, ball, projection, limit, flat=false) {
  let [dx,dy]=offset
  const length=Math.hypot(dx,dy)
  if(!length||limit<=0)return [0,0]
  if(length>limit){dx*=limit/length;dy*=limit/length}
  const intersects=t=>{
    const x=((raw[0]+dx*t)/viewport[0]*2-1)/projection[0]
    const y=(1-(raw[1]+dy*t)/viewport[1]*2)/projection[1]
    if(flat)return ball[2]<0&&(x*(-ball[2])-ball[0])**2+(y*(-ball[2])-ball[1])**2<=ball[3]**2
    const n=Math.hypot(x,y,1),dot=(x*ball[0]+y*ball[1]-ball[2])/n
    return dot>0&&ball[0]**2+ball[1]**2+ball[2]**2-dot**2<=ball[3]**2
  }
  const original=intersects(0)
  if(intersects(1)===original)return [dx,dy]
  let lo=0,hi=1
  for(let i=0;i<8;i++){const mid=(lo+hi)/2;if(intersects(mid)===original)lo=mid;else hi=mid}
  return [dx*lo,dy*lo]
}

export const BALL_OFFSET_GLSL=`
uniform vec4 cfzBallCamera;
uniform vec2 cfzProjection;
uniform float cfzBallOffsetLimit;
uniform float cfzRadial;
bool cfzRayHitsBall(vec2 pixel) {
  vec2 ndc=vec2(pixel.x/cfzViewport.x*2.0-1.0,1.0-pixel.y/cfzViewport.y*2.0);
  vec2 direction=ndc/cfzProjection;
  if(cfzRadial>1.5){
    vec2 delta=direction*(-cfzBallCamera.z)-cfzBallCamera.xy;
    return cfzBallCamera.z<0.0 && dot(delta,delta)<=cfzBallCamera.w*cfzBallCamera.w;
  }
  vec3 ray=normalize(vec3(direction,-1.0));
  float along=dot(ray,cfzBallCamera.xyz);
  return along>0.0 && dot(cfzBallCamera.xyz,cfzBallCamera.xyz)-along*along<=cfzBallCamera.w*cfzBallCamera.w;
}
vec2 cfzBoundOffset(vec2 pixel,vec2 requested) {
  float size=length(requested);
  if(size==0.0||cfzBallOffsetLimit<=0.0)return vec2(0.0);
  vec2 offset=requested*min(1.0,cfzBallOffsetLimit/size);
  bool original=cfzRayHitsBall(pixel);
  if(cfzRayHitsBall(pixel+offset)==original)return offset;
  float lo=0.0,hi=1.0;
  for(int i=0;i<8;i++){float mid=(lo+hi)*.5;if(cfzRayHitsBall(pixel+offset*mid)==original)lo=mid;else hi=mid;}
  return offset*lo;
}
`
