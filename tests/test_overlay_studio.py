import json
import os
import socket
import tempfile
import unittest
import shutil
import subprocess
from urllib.request import Request, urlopen

from browser_overlay import BrowserOverlayServer
from overlay_studio import OverlayStudioStore, runtime_js, sanitize_preset, studio_html, portrait_mirror_js, SIDE_PAIRS


class OverlayStudioTests(unittest.TestCase):
    def test_all_side_pairs_and_masters_are_saved_without_touching_central_elements(self):
        self.assertEqual(len(SIDE_PAIRS),10)
        raw={'sideMirror':True,'sideMirrorMasters':{'Name':'redName','Hp':'blueHp','timer':'timer'},
             'elements':{'timer':{'x':40},'blueName':{'y':12},'redName':{'color':'red'}}}
        with tempfile.TemporaryDirectory() as folder:
            store=OverlayStudioStore(os.path.join(folder,'preset.json'))
            store.set(raw,persist=True)
            value=OverlayStudioStore(store.path).get()
            self.assertTrue(value['sideMirror'])
            self.assertEqual(value['sideMirrorMasters'],{'Name':'redName','Hp':'blueHp'})
            self.assertEqual(value['elements'],raw['elements'])

    def test_portrait_link_is_opt_in_and_persists_with_existing_layout(self):
        original={'elements':{'bluePortrait':{'x':87},'timer':{'y':22}}}
        self.assertFalse(sanitize_preset(original)['portraitMirror'])
        with tempfile.TemporaryDirectory() as folder:
            store=OverlayStudioStore(os.path.join(folder,'preset.json'))
            store.set({**original,'portraitMirror':True,'portraitMirrorMaster':'redPortrait'},persist=True)
            result=OverlayStudioStore(store.path).get()
            self.assertTrue(result['portraitMirror'])
            self.assertEqual(result['portraitMirrorMaster'],'redPortrait')
            self.assertEqual(result['elements'],original['elements'])
        self.assertFalse(sanitize_preset({'portraitMirror':'false'})['portraitMirror'])
        self.assertEqual(sanitize_preset({'portraitMirrorMaster':'timer'})['portraitMirrorMaster'],'bluePortrait')

    @unittest.skipUnless(shutil.which('node'),'Node required for editor/runtime tests')
    def test_portrait_pair_edit_geometry_and_editor_syntax(self):
        editor=studio_html().split('<script>',1)[1].split('</script>',1)[0]
        script='const assert=require("node:assert/strict");\n'+portrait_mirror_js()+r'''
const p={portraitMirror:true,elements:{bluePortrait:{x:35,y:20,width:100,height:120,scale:0.8,rotate:12},redPortrait:{opacity:0.7},timer:{x:99}}};
studioMirrorEdit(p,'bluePortrait');
assert.deepEqual(p.elements.redPortrait,{x:-35,y:20,width:100,height:120,scale:0.8,rotate:-12,opacity:0.7});
p.elements.redPortrait.x=-70;studioMirrorEdit(p,'redPortrait');
assert.equal(p.elements.bluePortrait.x,70);assert.equal(p.portraitMirrorMaster,'redPortrait');
assert.equal(p.elements.timer.x,99);
p.portraitMirror=false;let before=JSON.stringify(p);studioMirrorEdit(p,'redPortrait');assert.equal(JSON.stringify(p),before);
for(const pair of Object.values(STUDIO_SIDE_PAIRS)){
 const p={sideMirror:true,elements:{[pair[0]]:{x:30,y:12,width:200,scale:0.9,fontSize:28,color:'blue'},[pair[1]]:{color:'red'},timer:{x:99}}};
 studioMirrorEdit(p,pair[0]);assert.equal(p.elements[pair[1]].x,-30);assert.equal(p.elements[pair[1]].fontSize,28);
 assert.equal(p.elements[pair[1]].color,'red');assert.equal(p.elements.timer.x,99);
 p.elements[pair[1]].x=-70;studioMirrorEdit(p,pair[1]);assert.equal(p.elements[pair[0]].x,70);
 assert(studioMirrorPairs(p).some(ordered=>ordered[0]===pair[1]&&ordered[1]===pair[0]));
}
for(const unit of [0.5,1,2]){
 const master={right:310*unit,top:70*unit},peer={left:1500*unit,top:95*unit};
 const position=studioMirrorPosition(master,peer,960*unit,unit,{x:-35,y:20});
 assert.equal(position.x,75);assert.equal(position.y,-5);
}
'''+ '\nnew Function('+json.dumps(editor)+');'
        result=subprocess.run(['node','-e',script],capture_output=True,text=True,encoding='utf8',timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    @unittest.skipUnless(shutil.which('node'),'Node required for runtime layout test')
    def test_runtime_mirrors_actual_rectangles_without_flipping_images(self):
        script=r'''
const assert=require('node:assert/strict'),vm=require('node:vm');
 for(const unit of [0.5,1,2])for(const master of ['bluePortrait','redPortrait','blueName','redName']){
 const nodes={};
 function node(x,y,w,h){
  const values={};return {style:{setProperty:(k,v)=>values[k]=v,getPropertyValue:k=>values[k]||'',removeProperty:k=>delete values[k]},values,
   getBoundingClientRect(){let [tx,ty]=(values.translate||'0 0').split(' ').map(parseFloat),s=Number(values.scale)||1;
    let width=(parseFloat(values.width)||w)*s*unit,height=(parseFloat(values.height)||h)*s*unit;
    let left=(x+tx)*unit,top=(y+ty)*unit;return {left,top,right:left+width,bottom:top+height,width,height}}};
 }
 nodes['#blueImg']=node(50,40,90,90);nodes['#redImg']=node(1530,90,140,140);
 nodes['#blueName']=node(300,120,170,40);nodes['#redName']=node(1400,160,200,40);
 nodes['.hud']={style:{removeProperty(){},setProperty(){}},offsetWidth:1920,getBoundingClientRect:()=>({width:1920*unit})};
 const context={URLSearchParams,location:{search:''},innerWidth:1920*unit,
   document:{querySelector:s=>nodes[s]||null,querySelectorAll:s=>nodes[s]?[nodes[s]]:[]},
   fetch:()=>new Promise(()=>{}),window:{addEventListener(){}}};
 vm.createContext(context);vm.runInContext(RUNTIME,context);
 const suffix=master.startsWith('blue')?master.slice(4):master.slice(3);
 const p={sideMirror:true,sideMirrorMasters:{[suffix]:master},elements:{[master]:{x:37,y:18,width:110,height:115,scale:1.25}}};
 const original=JSON.stringify(p);context.window.__overlayStudioApply(p);
 const blue=suffix==='Portrait'?'#blueImg':'#blueName',red=suffix==='Portrait'?'#redImg':'#redName';
 let b=nodes[blue].getBoundingClientRect(),r=nodes[red].getBoundingClientRect();
 assert(Math.abs(b.right+r.left-1920*unit)<1e-8);assert.equal(b.top,r.top);assert.equal(b.width,r.width);assert.equal(b.height,r.height);
 assert.equal(JSON.stringify(p),original);assert.equal(nodes['#redImg'].values.transform,undefined);
 context.window.__overlayStudioApply(p);
 assert.deepEqual(nodes[blue].getBoundingClientRect(),b);
 assert.deepEqual(nodes[red].getBoundingClientRect(),r);
 const snapshots=context.window.__overlayStudioMirrorSnapshots;
 for(const snapshot of snapshots){
  const pair=Object.values(__TEST_PAIRS__).find(pair=>pair.includes(snapshot.id));
  const source=p.sideMirrorMasters[pair[0].slice(4)]||pair[0];
  p.elements[snapshot.id]={...p.elements[source],...snapshot.position};
 }
 p.sideMirror=false;
 context.window.__overlayStudioApply(p);
 assert.deepEqual(nodes[blue].getBoundingClientRect(),b);assert.deepEqual(nodes[red].getBoundingClientRect(),r);
}
'''.replace('__TEST_PAIRS__',json.dumps(SIDE_PAIRS)).replace('RUNTIME',json.dumps(runtime_js()))
        result=subprocess.run(['node','-e',script],capture_output=True,text=True,encoding='utf8',timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_sanitize_rejects_unknown_elements_and_clamps_values(self):
        result = sanitize_preset({
            "name": "test",
            "elements": {
                "timer": {"x": 99999, "opacity": -4, "visible": False, "color": "#ffeeaa"},
                "notReal": {"x": 30},
            },
        })
        self.assertEqual(result["elements"]["timer"]["x"], 1920.0)
        self.assertEqual(result["elements"]["timer"]["opacity"], 0.0)
        self.assertFalse(result["elements"]["timer"]["visible"])
        self.assertNotIn("notReal", result["elements"])

    def test_store_persists_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "presets", "overlay.json")
            store = OverlayStudioStore(path)
            store.set({"elements": {"blueName": {"x": 25}}}, persist=True)
            loaded = OverlayStudioStore(path).get()
            self.assertEqual(loaded["elements"]["blueName"]["x"], 25.0)

    def test_editor_and_runtime_include_live_edit_contract(self):
        editor = studio_html()
        runtime = runtime_js()
        self.assertIn('id="importFile"', editor)
        self.assertIn('id="snap"', editor)
        self.assertIn("i.oninput", editor)
        self.assertIn("window.__overlayStudioApply=apply", runtime)

    def test_http_api_updates_sse_state_and_persists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            server = BrowserOverlayServer(port, path_resolver=lambda path: os.path.join(temp_dir, path))
            self.assertTrue(server.start())
            try:
                with urlopen(server.studio_url, timeout=3) as response:
                    self.assertIn("OVERLAY STUDIO", response.read().decode("utf-8"))
                with urlopen(server.url, timeout=3) as response:
                    overlay_html = response.read().decode("utf-8")
                self.assertIn('/studio-runtime.js', overlay_html)
                self.assertIn("window.__overlayStudioApply", overlay_html)
                payload = json.dumps({"elements": {"timer": {"x": 42}}}).encode("utf-8")
                request = Request(
                    f"http://127.0.0.1:{port}/api/studio/preset?persist=1",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=3) as response:
                    saved = json.loads(response.read().decode("utf-8"))
                self.assertEqual(saved["elements"]["timer"]["x"], 42.0)
                self.assertEqual(server.snapshot()["studioPreset"]["elements"]["timer"]["x"], 42.0)
                self.assertTrue(os.path.isfile(os.path.join(temp_dir, "presets", "overlay", "overlay_studio.json")))
            finally:
                server.stop()


if __name__ == "__main__":
    unittest.main()
