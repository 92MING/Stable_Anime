import os, sys
folder_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(folder_path, 'source'))

from engine.runtime.components import Camera, MeshRenderer
from engine.runtime.gameObj import GameObject
from engine.runtime.component import Component
from engine.engine import Engine
from engine.runtime.components import CameraController, CorrMapRenderer, SpriteInfo, EqualIntervalRotation
from engine.static import Mesh, Material_MTL, CorrespondMap, EngineMode, Texture, Material
from engine.static.enums import TextureFormat, TextureDataType, TextureFilter, TextureWrap, TextureInternalFormat, DefaultTextureType
from common_utils.path_utils import *


if __name__ == '__main__':

    class Sample(Engine):
        
        def beforePrepare(self):
            sphere_mesh = Mesh.Sphere()
            mat = Material.DefaultOpaqueMaterial()
            tex= Texture.Load(r'D:\Stable-Renderer\resources\example-3d-models\debug\debug_uv_texture.jpg'.replace('\\', '/'))
            mat.addDefaultTexture(tex, DefaultTextureType.DiffuseTex)
            
            camera = GameObject('Camera', position=[0, 0.68, 2.3])
            camera.addComponent(Camera, bgPrompt='no background')
            camera.transform.lookAt([0, 0.68, 0])
            #camera.addComponent(CameraController, defaultPos=[0, 0.68, 2.3], defaultLookAt=[0, 0.68, 0])
            
            ball = GameObject('ball', position=[0, 0.68, 0], scale=0.70)
            meshRenderer = ball.addComponent(MeshRenderer, mesh=sphere_mesh)
            meshRenderer.addMaterial(mat)
            
            rotation_interval = 360
            
            ball.addComponent(EqualIntervalRotation, interval=rotation_interval)
            
            self.corrmap = CorrespondMap(k=6)
            win_width, win_height = self.WindowManager.WindowSize
            tex = Texture(width=win_width, 
                          height=win_height, 
                          format=TextureFormat.RGBA,
                          data_type=TextureDataType.FLOAT,
                          min_filter=TextureFilter.NEAREST,
                          mag_filter=TextureFilter.NEAREST,
                          s_wrap=TextureWrap.REPEAT,
                          t_wrap=TextureWrap.REPEAT,
                          internal_format=TextureInternalFormat.RGBA32F,
                          data=self.RenderManager.GlobalBGNoise[0].cpu().numpy().tobytes(),
                          share_to_torch=True,)
            tex.load()
            mat = Material.DefaultTransparentMaterial()
            mat.addDefaultTexture(tex, DefaultTextureType.NoiseTex)
            
            corrmap_obj = GameObject('corrmap', position=[0, 0.68, 0], scale=0.85)
            corrmap_obj.addComponent(SpriteInfo, auto_spriteID=True, prompt='')
            corrmap_obj.addComponent(CorrMapRenderer, corrmaps=self.corrmap, materials=[mat,], use_texcoord_id=True)
            corrmap_obj.addComponent(EqualIntervalRotation, interval=rotation_interval)
            
        def beforeFrameBegin(self):    
            if self.RuntimeManager.FrameCount == 360:
                self.Exit()
        
        def beforeRelease(self):
            # self.corrmap.dump(OUTPUT_DIR, name='miku_corrmap')
            ...
            
    #baking_workflow = EXAMPLE_WORKFLOWS_DIR / 'bake.json'
    #baking_workflow = EXAMPLE_WORKFLOWS_DIR / 'no-normal-bake.json'
    #baking_workflow = EXAMPLE_WORKFLOWS_DIR / 'no-control-bake.json'
    baking_workflow = EXAMPLE_WORKFLOWS_DIR / 'no-mask-prompt-bake.json'
    Sample.Run(winSize=(512, 512),
               mode = EngineMode.BAKE,
               # mode = EngineMode.GAME,
               mapSavingInterval=1,
               baking_interval=8,
               needOutputMaps=True,
               disableComfyUI=True,
               diffuse_workflow=baking_workflow)
