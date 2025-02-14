import os, sys
source_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(source_dir)

import glm
import os.path

from engine.runtime.components import Camera, MeshRenderer
from engine.runtime.gameObj import GameObject
from engine.runtime.component import Component
from engine.engine import Engine
from engine.static import (Material, DefaultTextureType, Mesh, Texture, GLFW_Key)

from common_utils.path_utils import EXAMPLE_3D_MODEL_DIR, EXAMPLE_WORKFLOWS_DIR


if __name__ == '__main__':
    class ControlBoat(Component):
        '''Control the boat with W, A, S, D keys. The boat will move forward, backward, left, right.'''
        
        deceleration_rate: float = 0.98
        angular_deceleration_rate: float = 0.95
        
        acceleration: float = 0.05
        angular_acceleration: float = 5
        max_spd = 0.5
        max_angular_spd = 90
        
        velocity: glm.vec3 = glm.vec3(0)
        angular_velocity: float = 0
        
        _inputManager = None
        @property
        def inputManager(self):
            if self._inputManager is None:
                self._inputManager = self.engine.InputManager
            return self._inputManager
        
        _runtimeManager = None
        @property
        def runtimeManager(self):
            if self._runtimeManager is None:
                self._runtimeManager = self.engine.RuntimeManager
            return self._runtimeManager
        
        def update_physics(self):
            if glm.length(self.velocity) > 0.005:
                self.velocity *= self.deceleration_rate
                self.transform.position += (self.transform.forward + self.velocity) * self.runtimeManager.DeltaTime
            else:
                self.velocity = glm.vec3(0)
                
            if abs(self.angular_velocity) > 0.005:
                self.angular_velocity *= self.angular_deceleration_rate
                self.transform.rotateLocalY(self.angular_velocity * self.runtimeManager.DeltaTime)
            else:
                self.angular_velocity = 0
        
        def fixedUpdate(self):
            if self.inputManager.GetKey(GLFW_Key.W):
                self.velocity += self.transform.forward * self.acceleration
                
            if self.inputManager.GetKey(GLFW_Key.S):
                self.velocity -= self.transform.forward * self.acceleration
                
            if self.inputManager.GetKey(GLFW_Key.A):
                self.angular_velocity += self.angular_acceleration
             
            if self.inputManager.GetKey(GLFW_Key.D):
                self.angular_velocity -= self.angular_acceleration
                
            self.velocity = glm.clamp(self.velocity, -self.max_spd, self.max_spd)
            self.angular_velocity = -self.max_angular_spd if self.angular_velocity < -self.max_angular_spd else self.max_angular_spd if self.angular_velocity > self.max_angular_spd else self.angular_velocity
            
            self.update_physics()
    
    class AutoRotation(Component):
        def update(self):
            self.transform.rotateLocalY(2.5 * self.engine.RuntimeManager.DeltaTime)
    
    class Sample(Engine):
        def beforePrepare(self):

            boatMesh = Mesh.Load(os.path.join(EXAMPLE_3D_MODEL_DIR, 'boat', 'boat.obj'))
            boatMaterial = Material.DefaultOpaqueMaterial()

            boat_diffuse_tex = Texture.Load(os.path.join(EXAMPLE_3D_MODEL_DIR, 'boat', 'boatColor.png'))
            boatMaterial.addDefaultTexture(boat_diffuse_tex, DefaultTextureType.DiffuseTex)
            boatMaterial.addDefaultTexture(Texture.Load(os.path.join(EXAMPLE_3D_MODEL_DIR, 'boat', 'boatNormal.png')), DefaultTextureType.NormalTex)
            boatMaterial.addDefaultTexture(Texture.CreateNoiseTex(), DefaultTextureType.NoiseTex)
            
            boat = GameObject('Boat', position=[0, 0, 0])
            boat.addComponent(MeshRenderer, mesh=boatMesh, materials=boatMaterial)
            boat.addComponent(AutoRotation)
            
            # uncomment this line to control the boat
            # boat.addComponent(ControlBoat)
            
            initial_position = [0, 3, -3]
            camera = GameObject('Camera', position=initial_position)
            camera.addComponent(Camera)
            camera.transform.lookAt([0, 0, 0])

    img2img_boat_path = EXAMPLE_WORKFLOWS_DIR / 'boat-img2img-example.json'
    Sample.Run(winSize=(512, 512),
               mapSavingInterval=1,
               needOutputMaps=False,
               outputAICannyMap=False,
               saveSDColorOutput=False,
               disableComfyUI=False,
               default_workflow=img2img_boat_path)