from typing import Optional
import qrenderdoc as qrd
import renderdoc as rd
import os
import json
import sys
import array

def extract_string(tokenstr):
    s = ''
    for c in tokenstr:
        for i in range(4):
            shifted = (c >> (8 * i)) & 0xff
            if shifted == 0:
                break
            s += chr(shifted)
    return s

class spv:
    OpTypeInt = 21
    OpExtInstImport = 11
    OpExtInst = 12
    OpString = 7
    OpConstant = 43

def parse_spirv_resources(bytes):
    token_array = [x for x in array.array('I', bytes)]
    token_array = token_array[5:]

    constants = dict()
    strings = dict()
    int_types = set()
    nonsemantic = 0

    resources = []
    name = 'shader.dxil'

    offset = 0
    while offset < len(token_array):
        opcode : int = token_array[offset] & 0xffff
        oplen = token_array[offset] >> 16
        args = token_array[offset + 1 : offset + oplen]
        offset += oplen
        match opcode:
            case spv.OpTypeInt:
                int_types.add(args[0])
            case spv.OpString:
                s = extract_string(args[1:])
                if s.endswith('.dxil') or s.endswith('.dxbc'):
                    name = s
                else:
                    strings[args[0]] = s
            case spv.OpConstant:
                if args[0] in int_types:
                    constants[args[1]] = args[2]
            case spv.OpExtInstImport:
                if extract_string(args[1:]) == 'NonSemantic.dxil-spirv.signature':
                    nonsemantic = args[0]
            case spv.OpExtInst:
                if args[2] == nonsemantic and args[3] == 0:
                    kind = strings[args[4]]
                    index = constants[args[5]]
                    pushoffset = constants[args[6]]
                    pushsize = constants[args[7]]
                    resources.append((kind, index, pushoffset, pushsize))
            case _:
                pass


    return resources, name

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
            return "???"

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

def convert_address(addr):
    match addr:
        case rd.AddressMode.Wrap:
            return "WRAP";
        case rd.AddressMode.ClampEdge:
            return "CLAMP"
        case rd.AddressMode.Mirror:
            return "MIRROR"
        case rd.AddressMode.MirrorOnce | rd.AddressMode.MirrorClamp:
            return "MIRROR_ONCE"
        case rd.AddressMode.ClampBorder:
            return "BORDER"
        case _:
            return "???"

def convert_comparison_func(func):
    match func:
        case rd.CompareFunction.AlwaysTrue:
            return "ALWAYS"
        case rd.CompareFunction.Never:
            return "NEVER"
        case rd.CompareFunction.Less:
            return "LESS"
        case rd.CompareFunction.LessEqual:
            return "LESS_EQUAL"
        case rd.CompareFunction.Greater:
            return "GREATER"
        case rd.CompareFunction.GreaterEqual:
            return "GREATER_EQUAL"
        case rd.CompareFunction.Equal:
            return "EQUAL"
        case rd.CompareFunction.NotEqual:
            return "NOT_EQUAL"
        case _:
            return "???"

def convert_filter(filt):
    if filt.minify == rd.FilterMode.Anisotropic or filt.magnify == rd.FilterMode.Anisotropic:
        match filt.filter:
            case rd.FilterFunction.Normal:
                return 'ANISOTROPIC'
            case rd.FilterFunction.Comparison:
                return 'COMPARISON_ANISOTROPIC'
            case rd.FilterFunction.Minimum:
                return 'MINIMUM_ANISOTROPIC'
            case rd.FilterFunction.Maximum:
                return 'MAXIMUM_ANISOTROPIC'
            case _:
                return '???'

    order = [
        filt.minify == rd.FilterMode.Point,
        filt.magnify == rd.FilterMode.Point,
        filt.mip == rd.FilterMode.Point
    ]

    kinds = [ 'MIN', 'MAG', 'MIP' ]
    res = ''

    for i in range(3):
        emit_kind = order[i + 1] != order[i] if i < 2 else True
        res += kinds[i]
        if emit_kind:
            res += '_'
            res += 'POINT' if order[i] else 'LINEAR'
        if i < 2:
            res += '_'

    match filt.filter:
        case rd.FilterFunction.Comparison:
            res = 'COMPARISON_' + res
        case rd.FilterFunction.Minimum:
            res = 'MINIMUM_' + res
        case rd.FilterFunction.Maximum:
            res = 'MAXIMUM_' + res

    return res

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

def lookup_bda(ctx : qrd.CaptureContext, bda, max_size):
    buffers : List[rd.BufferDescription] = ctx.GetBuffers()
    for buf in buffers:
        if bda >= buf.gpuAddress and bda < buf.gpuAddress + buf.length:
            avail_len = buf.gpuAddress + buf.length - bda
            avail_len = min(avail_len, max_size)
            return buf.resourceId, bda - buf.gpuAddress, avail_len
    return 0, 0, 0

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

    spirv_resources, dxil_name = parse_spirv_resources(reflection.rawBytes)
    push = [x for x in array.array('I', pso.pushconsts)]

    ro : List[rd.UsedDescriptor] = generic_pso.GetReadOnlyResources(rd.ShaderStage.Compute)
    rw : List[rd.UsedDescriptor] = generic_pso.GetReadWriteResources(rd.ShaderStage.Compute)
    cbv : List[rd.UsedDescriptor] = generic_pso.GetConstantBlocks(rd.ShaderStage.Compute)
    samplers : List[rd.UsedDescriptor] = generic_pso.GetSamplers(rd.ShaderStage.Compute)

    unique_texture_resources = {}
    unique_buffer_resources = {}

    for kind in [ro, rw]:
        for r in kind:
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
                    tex.uav = True
                else:
                    tex.srv = True

    for res in spirv_resources:
        # Register root descriptors
        kind = res[0]
        index = res[1]
        pushoffset = res[2] // 4
        pushsize = res[3] // 4
        if kind == 'SRV' or kind == 'UAV' or kind == 'CBV':
            bda = push[pushoffset] | (push[pushoffset + 1] << 32)
            resid, offset, size = lookup_bda(ctx, bda, 0x10000 if kind == 'CBV' else 0xffffffff)
            if resid != 0:
                if resid not in unique_buffer_resources:
                    unique_buffer_resources[resid] = BufferState(resid)
                buf = unique_buffer_resources[resid]
                buf.add_accessed_range(offset, offset + size)
                if kind == 'UAV':
                    buf.uav = True
                else:
                    buf.srv = True
            else:
                print(f'Failed to lookup BDA {hex(bda)}')

    blob_index = 1
    dir_path = '/tmp'

    # Dump accessed buffers to file
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

    capture['CS'] = dxil_name
    capture['RootSignature'] = 'rootsig.rs'
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
                'MipLevels' : img.desc.mips,
                'DepthOrArraySize' : max(img.desc.depth, img.desc.arraysize),
                'FlagUAV' : uav,
                'PixelSize' : img.base_format.ElementSize(),
                'data': img.paths
            }
            resources.append(res)

    srvs = []
    uavs = []
    cbvs = []
    desc_samplers = []
    used_resource_heap_offsets = set()
    used_sampler_heap_offsets = set()

    for r in samplers:
        print('Sampler ...')
        block = reflection.samplers[r.access.index]
        samp = r.sampler
        # Skip immutable samplers
        if block.bindArraySize == 1 or samp.creationTimeConstant:
            continue
        if r.access.arrayElement in used_sampler_heap_offsets:
            continue
        print('Emitting Sampler ...')
        used_sampler_heap_offsets.add(r.access.arrayElement)
        desc = {
            'HeapOffset' : r.access.arrayElement,
            'AddressU' : convert_address(samp.addressU),
            'AddressV' : convert_address(samp.addressV),
            'AddressW' : convert_address(samp.addressW),
            'ComparisonFunc' : convert_comparison_func(samp.compareFunction),
            'MaxAnisotropy' : samp.maxAnisotropy,
            'MinLOD' : samp.minLOD,
            'MaxLOD' : samp.maxLOD,
            'MipLODBias' : samp.mipBias,
            'Filter' : convert_filter(samp.filter)
        }

        if samp.UseBorder():
            desc['BorderColor'] = [ x for x in samp.borderColorValue.float ]
        desc_samplers.append(desc)

    for r in cbv:
        block = reflection.constantBlocks[r.access.index]
        if block.compileConstants or (not block.bufferBacked):
            continue
        if block.bindArraySize == 1:
            print('PushDescriptor path not supported yet.')
            continue
        if r.access.arrayElement in used_resource_heap_offsets:
            continue
        used_resource_heap_offsets.add(r.access.arrayElement)

        print('shaderName: {}'.format(block.name))
        name = f'cbv{blob_index}'
        path = name + '.bin'
        blob_index += 1
        ctx.Replay().BlockInvoke(lambda replayer :
                                 dump_binary_to_file(os.path.join(dir_path, path),
                                                     replayer.GetBufferData(r.descriptor.resource,
                                                                            r.descriptor.byteOffset,
                                                                            r.descriptor.byteSize)))
        res = {
            'name' : path,
            'Dimension' : 'BUFFER',
            'Width' : r.descriptor.byteSize,
            'data' : [ path ]
        }
        resources.append(res)

        cbv = {
            'HeapOffset' : r.access.arrayElement,
            'Resource' : name,
            'BufferLocation' : 0,
            'SizeInBytes' : r.descriptor.byteSize
        }
        cbvs.append(cbv)

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

    capture['Resources'] = resources
    capture['SRV'] = srvs
    capture['UAV'] = uavs
    capture['CBV'] = cbvs
    capture['Sampler'] = desc_samplers

    root_parameters = []

    for res in spirv_resources:
        kind = res[0]
        index = res[1]
        pushoffset = res[2] // 4
        pushsize = res[3] // 4
        if kind == 'SRV' or kind == 'UAV' or kind == 'CBV':
            bda = push[pushoffset] | (push[pushoffset + 1] << 32)
            resid, offset, _ = lookup_bda(ctx, bda, 0x10000 if kind == 'CBV' else 0xffffffff)
            if resid != 0:
                root_parameters.append({ 'index' : index, 'type' : kind, 'Resource' : unique_buffer_resources[resid].name, 'offset' : offset })
            else:
                print(f'Failed to lookup BDA {hex(bda)}, cannot dump parameter {index}')
        if kind == 'ResourceTable' or kind == 'SamplerTable':
            root_parameters.append({ 'index' : index, 'type' : kind, 'offset' : push[pushoffset] })
        if kind == 'Constant':
            root_parameters.append({ 'index' : index, 'type' : kind, 'offset' : pushoffset, 'data' : push[pushoffset : pushoffset + pushsize] })

    capture['RootParameters'] = root_parameters

    with open(os.path.join(dir_path, 'capture.json'), 'w') as f:
        print(json.dumps(capture, indent = 4), file = f)

def register(version : str, ctx : qrd.CaptureContext):
    print('Loading exporter for version {}'.format(version))
    ctx.Extensions().RegisterWindowMenu(qrd.WindowMenu.Window, ["Export vkd3d-proton to D3D12 Replayer Capture"], export_callback)

def unregister():
    print('Unregistering exporter')

def main():
    with open(sys.argv[1], "rb") as f:
        parse_spirv(f.read())

if __name__ == '__main__':
    main()