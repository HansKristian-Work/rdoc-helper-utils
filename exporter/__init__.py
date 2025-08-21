from typing import Optional
import qrenderdoc as qrd
import renderdoc as rd
import os
import json

def is_buffer(desc_type):
    match desc_type:
        case rd.DescriptorType.Buffer:
            return True
        case rd.DescriptorType.TypedBuffer:
            return True
        case rd.DescriptorType.ReadWriteTypedBuffer:
            return True
        case rd.DescriptorType.ReadWriteBuffer:
            return True
        case rd.DescriptorType.ConstantBuffer:
            return True
        case _:
            return False

def is_image(desc_type):
    match desc_type:
        case rd.DescriptorType.Image:
            return True
        case rd.DescriptorType.ReadWriteImage:
            return True
        case _:
            return False

def is_uav(desc_type):
    match desc_type:
        case rd.DescriptorType.ReadWriteTypedBuffer:
            return True
        case rd.DescriptorType.ReadWriteBuffer:
            # TODO: This depends on root signature info.
            return True
        case rd.DescriptorType.ReadWriteImage:
            return True
        case _:
            return False

def is_typed(desc_type):
    match desc_type:
        case rd.DescriptorType.TypedBuffer:
            return True
        case rd.DescriptorType.Image:
            return True
        case rd.DescriptorType.ReadWriteTypedBuffer:
            return True
        case rd.DescriptorType.ReadWriteImage:
            return True
        case _:
            return False

def to_view_type(view_type):
    match view_type:
        case rd.TextureType.Buffer:
            return 'BUFFER'
        case rd.TextureType.Texture1D:
            return 'TEXTURE1D'
        case rd.TextureType.Texture1DArray:
            return 'TEXTURE1DARRAY'
        case rd.TextureType.Texture2D:
            return 'TEXTURE2D'
        case rd.TextureType.Texture2DArray:
            return 'TEXTURE2DARRAY'
        case rd.TextureType.Texture2DMS:
            return 'TEXTURE2DMS'
        case rd.TextureType.Texture2DMSArray:
            return 'TEXTURE2DMSARRAY'
        case rd.TextureType.TextureCube:
            return 'TEXTURECUBE'
        case rd.TextureType.TextureCubeArray:
            return 'TEXTURECUBEARRAY'
        case rd.TextureType.Texture3D:
            return 'TEXTURE3D'
        case _:
            return str(view_type)

def view_type_has_mip_range(view_type, uav):
    return (not uav) and view_type != rd.TextureType.Texture2DMS and view_type != rd.TextureType.Texture2DMSArray

def view_type_has_mip_slice(view_type, uav):
    return uav and view_type != rd.TextureType.Texture2DMS and view_type != rd.TextureType.Texture2DMSArray

def view_type_has_wsize(view_type, uav):
    return uav and view_type == rd.TextureType.Texture3D

def view_type_has_array_range(view_type, uav):
    match view_type:
        case rd.TextureType.Texture1DArray:
            return True
        case rd.TextureType.Texture2DArray:
            return True
        case rd.TextureType.Texture2DMSArray:
            return True
        case _:
            return False

def view_type_has_cube_range(view_type, uav):
    return view_type == rd.TextureType.TextureCubeArray

class BufferState():
    def __init__(self, res):
        self.start_offset = 0xffffffff
        self.end_offset = 0
        self.srv = False
        self.uav = False
        self.name = ''
        self.path = ''
        self.resource = res

    def add_accessed_range(self, start, end):
        if start < self.start_offset:
            self.start_offset = start
        if end > self.end_offset:
            self.end_offset = end

    def align(self):
        self.start_offset = self.start_offset & ~0xffff

class TextureState():
    def __init__(self, res):
        self.formats = []
        self.base_format = None
        self.srv = False
        self.uav = False
        self.name = ''
        self.paths = []
        self.resource = res
        self.desc = None

    def add_view_format(self, fmt):
        self.formats.append(fmt)

def dump_binary_to_file(path, binary_data):
    with open(path, 'wb') as f:
        f.write(binary_data)

def export_callback(ctx : qrd.CaptureContext, data):
    print('Trying to export ...')
    eid = ctx.CurEvent()
    print('Got EID {}'.format(eid))

    pso : renderdoc.VKState = ctx.CurVulkanPipelineState()
    if pso is None:
        print('Could not find a Vulkan pipeline state.')
        return

    generic_pso : renderdoc.PipeState = ctx.CurPipelineState()
    reflection : rd.ShaderReflection = generic_pso.GetShaderReflection(rd.ShaderStage.Compute)
    print(reflection)

    print('Grabbing push constants')
    push = pso.pushconsts
    print(push)

    ro : List[rd.UsedDescriptor] = generic_pso.GetReadOnlyResources(rd.ShaderStage.Compute)
    rw : List[rd.UsedDescriptor] = generic_pso.GetReadWriteResources(rd.ShaderStage.Compute)

    unique_texture_resources = {}
    unique_buffer_resources = {}

    for kind in [ro, rw]:
        for r in kind:
            print('shaderName: {}'.format(reflection.readWriteResources[r.access.index].name))
            print('ArrayElement:', r.access.arrayElement)

            if is_buffer(r.descriptor.type):
                if r.descriptor.resource not in unique_buffer_resources:
                    unique_buffer_resources[r.descriptor.resource] = BufferState(r.descriptor.resource)

                # We need more complex reflection to know if a resource is SRV or UAV. For now, assume UAV.
                buf = unique_buffer_resources[r.descriptor.resource]
                buf.add_accessed_range(r.descriptor.byteOffset, r.descriptor.byteSize + r.descriptor.byteOffset)
                if is_uav(r.descriptor.type):
                    buf.uav = True
                else:
                    buf.srv = True 
            elif is_image(r.descriptor.type):
                if r.descriptor.resource not in unique_texture_resources:
                    unique_texture_resources[r.descriptor.resource] = TextureState(r.descriptor.resource)

                tex = unique_texture_resources[r.descriptor.resource]
                tex.add_view_format(r.descriptor.format)
                if is_uav(r.descriptor.type):
                    tex.srv = True
                else:
                    tex.uav = True

    blob_index = 1
    dir_path = '/tmp'

    # Dump buffers to file
    for buf in unique_buffer_resources.values():
        buf.align()
        buf.name = f'buffer{blob_index}'
        path = buf.name + '.bin'
        buf.path = path
        blob_index += 1
        print('Dumping buffer to: {}'.format(path))
        ctx.Replay().BlockInvoke(lambda replayer :
                                 dump_binary_to_file(os.path.join(dir_path, path),
                                                     replayer.GetBufferData(buf.resource, buf.start_offset, buf.end_offset - buf.start_offset)))

    # Dump textures to file
    textures : List[rd.TextureDescription] = ctx.GetTextures()
    for img in unique_texture_resources.values():
        img.name = f'texture{blob_index}'
        blob_index += 1
        for tex in textures:
            img.base_format = tex.format
            if tex.resourceId == img.resource:
                for mip in range(tex.mips):
                    # Dump mips separately. Fuse all slices together.
                    path = f'{img.name}_mip{mip}.bin'
                    print('Dumping texture to: {}'.format(path))
                    img.paths.append(path)
                    img.desc = tex
                    with open(os.path.join(dir_path, path), 'wb') as f:
                        for layer in range(max(tex.depth, tex.arraysize)):
                            sub = rd.Subresource()
                            sub.mip = mip
                            sub.slice = layer
                            sub.sample = 0
                            ctx.Replay().BlockInvoke(
                                    lambda replayer :
                                    f.write(replayer.GetTextureData(img.resource, sub)))

    capture = {}

    capture['CS'] = 'shader.dxil'
    capture['RootSignature'] = 'rs.dxil'
    resources = []
    capture['Dispatch'] = [1, 1, 1]

    for buf in unique_buffer_resources.values():
        for uav in range(2):
            if uav == 0 and (not buf.srv):
                continue
            if uav == 1 and (not buf.uav):
                continue
            res = {
                'name' : buf.name + ('.srv' if uav == 0 else '.uav'),
                'Dimension' : 'BUFFER',
                'Width' : buf.end_offset - buf.start_offset,
                'FlagUAV' : uav,
                'data' : [ buf.path ]
            }
            resources.append(res)

    for img in unique_texture_resources.values():
        for uav in range(2):
            if uav == 0 and (not img.srv):
                continue
            if uav == 1 and (not img.uav):
                continue
            res = {
                'name' : img.name + ('.srv' if uav == 0 else '.uav'),
                'Dimension' : f'TEXTURE{img.desc.dimension}D',
                'Width' : img.desc.width,
                'Height' : img.desc.height,
                'Format' : img.base_format.Name(),
                'DepthOrArraySize' : max(img.desc.depth, img.desc.arraysize),
                'FlagUAV' : uav,
                'PixelSize' : img.base_format.ElementSize(),
                'data': img.paths
            }
            resources.append(res)

    capture['Resources'] = resources

    srvs = []
    uavs = []
    used_resource_heap_offsets = set()

    for kind in [ro, rw]:
        for r in kind:
            desc = { 'HeapOffset' : r.access.arrayElement }
            # Can happen for aliased resources for vectorization purposes, just ignore
            if r.access.arrayElement in used_resource_heap_offsets:
                continue
            used_resource_heap_offsets.add(r.access.arrayElement)

            uav = is_uav(r.descriptor.type)

            if is_buffer(r.descriptor.type):
                buf = unique_buffer_resources[r.descriptor.resource]
                desc['Resource'] = buf.name + ('.uav' if uav else '.srv')
                desc['ViewDimension'] = 'BUFFER'

                if is_typed(r.descriptor.type):
                    desc['Format'] = r.descriptor.format.Name()
                    element_size = r.descriptor.format.ElementSize()
                    if (r.descriptor.byteOffset - buf.start_offset) % element_size != 0:
                        print('TexelBuffer does not align properly to buffer start. Is game using non 64 KiB alignment?')
                    desc['FirstElement'] = (r.descriptor.byteOffset - buf.start_offset) // element_size
                    desc['NumElements'] = r.descriptor.byteSize // element_size
                else:
                    # TODO: Figure out if we need to emit BAB or structured. Just assume plain uint structured for now.
                    element_size = 4
                    desc['FirstElement'] = (r.descriptor.byteOffset - buf.start_offset) // element_size
                    desc['NumElements'] = r.descriptor.byteSize // element_size
                    desc['StructureByteStride'] = 4

            elif is_image(r.descriptor.type):
                img = unique_texture_resources[r.descriptor.resource]
                desc['Resource'] = img.name + ('.uav' if uav else '.srv')
                desc['ViewDimension'] = to_view_type(r.descriptor.textureType)

                if view_type_has_mip_range(r.descriptor.textureType, uav):
                    desc['MostDetailedMip'] = r.descriptor.firstMip
                    desc['MipLevels'] = r.descriptor.numMips
                    desc['ResourceMinLODClamp'] = r.descriptor.minLODClamp

                if view_type_has_mip_slice(r.descriptor.textureType, uav):
                    desc['MipSlice'] = r.descriptor.firstMip

                if view_type_has_array_range(r.descriptor.textureType, uav):
                    desc['FirstArraySlice'] = r.descriptor.firstSlice
                    desc['ArraySize'] = r.descriptor.numSlices

                if view_type_has_cube_range(r.descriptor.textureType, uav):
                    desc['First2DArrayFace'] = 0
                    desc['NumCubes'] = 0

                if view_type_has_wsize(r.descriptor.textureType, uav):
                    desc['FirstWSlice'] = r.descriptor.firstSlice
                    desc['WSize'] = r.descriptor.numSlices

            if uav:
                uavs.append(desc)
            else:
                srvs.append(desc)

    capture['SRV'] = srvs
    capture['UAV'] = uavs

    with open(os.path.join(dir_path, 'capture.json'), 'w') as f:
        print(json.dumps(capture, indent = 4), file = f)

    #buffers : List[rd.BufferDescription] = ctx.GetBuffers()
    #for buf in buffers:
    #    print('Buffer {} : BDA {}, length {}'.format(buf.resourceId, buf.gpuAddress, buf.length))
    #    #ctx.Replay().BlockInvoke(lambda replayer : print(replayer.GetBufferData(r.descriptor.resource, r.descriptor.byteOffset, r.descriptor.byteSize)))

def register(version : str, ctx : qrd.CaptureContext):
    print('Loading exporter for version {}'.format(version))
    ctx.Extensions().RegisterWindowMenu(qrd.WindowMenu.Window, ["Export D3D12 Replayer Capture"], export_callback)

def unregister():
    print('Unregistering exporter')
