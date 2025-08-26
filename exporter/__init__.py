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
    int_types = dict()
    nonsemantic = 0

    resources = []
    name = 'shader.dxil'
    root_signature_binary = b''

    offset = 0
    while offset < len(token_array):
        opcode : int = token_array[offset] & 0xffff
        oplen = token_array[offset] >> 16
        args = token_array[offset + 1 : offset + oplen]
        offset += oplen
        match opcode:
            case spv.OpTypeInt:
                int_types[args[0]] = args[1]
            case spv.OpString:
                s = extract_string(args[1:])
                if s.endswith('.dxil') or s.endswith('.dxbc'):
                    name = s
                else:
                    strings[args[0]] = s
            case spv.OpConstant:
                if args[0] in int_types:
                    constants[args[1]] = (args[0], args[2])
            case spv.OpExtInstImport:
                if extract_string(args[1:]) == 'NonSemantic.dxil-spirv.signature':
                    nonsemantic = args[0]
            case spv.OpExtInst:
                if args[2] == nonsemantic and args[3] == 0:
                    kind = strings[args[4]]
                    index = constants[args[5]][1]
                    pushoffset = constants[args[6]][1]
                    pushsize = constants[args[7]][1]
                    resources.append((kind, index, pushoffset, pushsize))
                elif args[2] == nonsemantic and args[3] == 1:
                    if strings[args[4]] == 'RootSignature':
                        args = args[5:]
                        for arg in args:
                            c = constants[arg]
                            value : int = c[1]
                            bitwidth = int_types[c[0]]
                            root_signature_binary += value.to_bytes(bitwidth // 8, byteorder = 'little')

    return resources, name, root_signature_binary

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

class BufferRange():
    def __init__(self, start, end):
        self.start_offset = start
        self.end_offset = end
        self.ro = False
        self.rw = False
        self.name = ''
        self.path = ''

class BufferState():
    def __init__(self, res):
        self.ranges = []
        self.resource = res

    def add_accessed_range(self, start, end, is_uav):
        existing = self.find_overlapping_range(start, end)
        if existing:
            existing.start_offset = min(existing.start_offset, start)
            existing.end_offset = max(existing.end_offset, end)
        else:
            existing = BufferRange(start, end)
            self.ranges.append(existing)

        if is_uav:
            existing.rw = True
        else:
            existing.ro = True

    def align(self):
        # Core buffer alignment is 64 KiB in D3D12 (without the very latest AgilitySDK)
        # Need this to ensure that alignments for raw buffers work out.
        for buf_range in self.ranges:
            buf_range.start_offset = buf_range.start_offset & ~0xffff

    def find_overlapping_range(self, start, end):
        for buf_range in self.ranges:
            if start < buf_range.end_offset and end > buf_range.start_offset:
                return buf_range
        return None

    def find_matching_range(self, offset, is_uav):
        for buf_range in self.ranges:
            if offset >= buf_range.start_offset and offset < buf_range.end_offset:
                if (is_uav and buf_range.rw) or (not is_uav and buf_range.ro):
                    return buf_range
        return None

class TextureState():
    def __init__(self, res):
        self.formats = []
        self.base_format = None
        self.ro = False
        self.rw = False
        self.name = ''
        self.paths = []
        self.resource = res
        self.desc = None

    def add_view_format(self, fmt):
        if fmt not in self.formats:
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

def write_output_u32(out_object, in_bytes):
    out_object = array.array('I', in_bytes)

def to_d3d12_format(fmt : rd.ResourceFormat, is_depth):
    match fmt.type:
        case rd.ResourceFormatType.D16S8:
            # There is no D16S8 really.
            return 'R16_TYPELESS' if is_depth else 'R16_UNORM'
        case rd.ResourceFormatType.D24S8:
            return 'R24G8_TYPELESS' if is_depth else 'R24_UNORM_X8_TYPELESS'
        case rd.ResourceFormatType.D32S8:
            return 'R32G8X24_TYPELESS' if is_depth else 'R32_FLOAT_X8X24_TYPELESS'

    # There is no plain D24 in D3D12 iirc ...
    name = fmt.Name()
    if name == 'D32':
        return 'R32_TYPELESS' if is_depth else 'R32_FLOAT'
    elif name == 'D16':
        return 'R16_TYPELESS' if is_depth else 'R16_UNORM'
    else:
        return name

def to_d3d12_pixel_size(fmt : rd.ResourceFormat):
    match fmt.type:
        case rd.ResourceFormatType.D32S8:
            return 8
        case rd.ResourceFormatType.D24S8:
            return 4
        case _:
            return fmt.ElementSize()

def export_callback(ctx : qrd.CaptureContext, data):
    print('Trying to export ...')
    eid = ctx.CurEvent()
    print('Got EID {}'.format(eid))

    if eid == 0:
        print('Cannot capture EID 0')
        return

    pso : renderdoc.VKState = ctx.CurVulkanPipelineState()
    if pso is None:
        print('Could not find a Vulkan pipeline state.')
        return

    if not pso.compute:
        print('Current PSO is not a Vulkan compute shader.')
        return

    generic_pso : renderdoc.PipeState = ctx.CurPipelineState()

    reflection : rd.ShaderReflection = generic_pso.GetShaderReflection(rd.ShaderStage.Compute)

    spirv_resources, dxil_name, root_signature_binary = parse_spirv_resources(reflection.rawBytes)
    push = [x for x in array.array('I', pso.pushconsts)]

    ro : List[rd.UsedDescriptor] = generic_pso.GetReadOnlyResources(rd.ShaderStage.Compute)
    rw : List[rd.UsedDescriptor] = generic_pso.GetReadWriteResources(rd.ShaderStage.Compute)
    cbv : List[rd.UsedDescriptor] = generic_pso.GetConstantBlocks(rd.ShaderStage.Compute)
    samplers : List[rd.UsedDescriptor] = generic_pso.GetSamplers(rd.ShaderStage.Compute)

    action_description : rd.ActionDescription = ctx.GetAction(eid)

    if not action_description:
        print('There is no action description')
        return

    if not action_description.dispatchDimension:
        print('Dispatch dimension is not defined')
        return

    unique_texture_resources = {}
    unique_buffer_resources = {}

    # Very ugly special case for offset buffers. We'll have to rewrite texel buffer ranges as needed.
    # Goes away with descriptor buffer of course.
    # The offset buffer is always set 1, binding 1 under normal execution.
    offset_buffer = None
    for r in rw:
        res = reflection.readWriteResources[r.access.index]
        if res.bindArraySize == 1:
            if r.descriptor.type == rd.DescriptorType.ReadWriteBuffer and res.fixedBindNumber == 1 and res.fixedBindSetOrSpace == 1:
                print('Found legacy offset buffer, dumping ...')
                ctx.Replay().BlockInvoke(lambda replayer :
                    write_output_u32(offset_buffer, replayer.GetBufferData(
                        r.descriptor.resource, r.descriptor.byteOffset, r.descriptor.byteSize)))
                break

    for kind in [ro, rw]:
        for r in kind:
            if is_uav(r.descriptor.type):
                res = reflection.readWriteResources[r.access.index]
            else:
                res = reflection.readOnlyResources[r.access.index]

            name = res.name

            if res.bindArraySize == 1:
                continue

            if is_buffer(r.descriptor.type):
                if r.descriptor.resource not in unique_buffer_resources:
                    unique_buffer_resources[r.descriptor.resource] = BufferState(r.descriptor.resource)

                # Turbo-hacky handshake with vkd3d-proton
                force_srv = 'SRV' in name
                uav = is_uav(r.descriptor.type) and (not force_srv)
                buf = unique_buffer_resources[r.descriptor.resource]

                if is_typed(r.descriptor.type) and offset_buffer:
                    # Rewrite the offset / size to match the offset buffer values.
                    # Ignore offset buffer for SSBO since no driver should hit that path anymore.
                    offset = r.descriptor.byteOffset + r.descriptor.format.ElementSize() * offset_buffer[4 * r.access.arrayElement + 2]
                    size = r.descriptor.format.ElementSize() * offset_buffer[4 * r.access.arrayElement + 3]
                else:
                    offset = r.descriptor.byteOffset
                    size = r.descriptor.byteSize

                buf.add_accessed_range(offset, offset + size, uav)

            elif is_image(r.descriptor.type):
                if r.descriptor.resource not in unique_texture_resources:
                    unique_texture_resources[r.descriptor.resource] = TextureState(r.descriptor.resource)

                tex = unique_texture_resources[r.descriptor.resource]
                tex.add_view_format(r.descriptor.format)
                if is_uav(r.descriptor.type):
                    tex.rw = True
                else:
                    tex.ro = True

    for res in spirv_resources:
        print(res)
        # Register root descriptors
        kind = res[0]
        index = res[1]
        pushoffset = res[2] // 4
        pushsize = res[3] // 4
        if kind == 'SRV' or kind == 'UAV' or kind == 'CBV':
            bda = push[pushoffset] | (push[pushoffset + 1] << 32)
            resid, offset, size = lookup_bda(ctx, bda, 0x10000 if kind == 'CBV' else 0xffffffff)
            print(f'Looking up BDA {hex(bda)} -> {resid}, offset {offset}, size {size}')
            if resid != 0:
                if resid not in unique_buffer_resources:
                    unique_buffer_resources[resid] = BufferState(resid)
                buf = unique_buffer_resources[resid]
                buf.add_accessed_range(offset, offset + size, kind == 'UAV')
                print(f'Registering BDA access of type {kind}')
            else:
                print(f'Failed to lookup BDA {hex(bda)}')

    blob_index = 1
    dir_path = '/tmp'

    ctx.SetEventID([], eid - 1, eid - 1)

    # Dump accessed buffers to file
    for buf in unique_buffer_resources.values():
        buf.align()
        for buf_range in buf.ranges:
            # Dump every unique subrange
            buf_range.name = f'buffer{blob_index}'
            path = buf_range.name + '.bin'
            buf_range.path = path
            blob_index += 1
            print(f'Dumping buffer to: {path}')
            ctx.Replay().BlockInvoke(lambda replayer :
                                    dump_binary_to_file(os.path.join(dir_path, path),
                                                        replayer.GetBufferData(buf.resource, buf_range.start_offset, buf_range.end_offset - buf_range.start_offset)))

    # Dump textures to file
    textures : List[rd.TextureDescription] = ctx.GetTextures()
    for img in unique_texture_resources.values():
        img.name = f'texture{blob_index}'
        blob_index += 1
        for tex in textures:
            if tex.resourceId == img.resource:
                img.base_format = tex.format
                for mip in range(tex.mips):
                    # Dump mips separately. Fuse all slices together.
                    path = f'{img.name}_mip{mip}.bin'
                    print(f'Dumping texture to: {path}')
                    img.paths.append(path)
                    img.desc = tex
                    img.creationFlags = tex.creationFlags
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

    dump_binary_to_file(os.path.join(dir_path, 'rootsig.rs'), root_signature_binary)

    capture['CS'] = dxil_name
    capture['RootSignature'] = 'rootsig.rs'
    resources = []
    dispatch_dim = action_description.dispatchDimension
    capture['Dispatch'] = [dispatch_dim[0], dispatch_dim[1], dispatch_dim[2]]

    for buf in unique_buffer_resources.values():
        for buf_range in buf.ranges:
            for uav in range(2):
                if uav == 0 and (not buf_range.ro):
                    continue
                if uav == 1 and (not buf_range.rw):
                    continue
                res = {
                    'name' : buf_range.name + ('.ro' if uav == 0 else '.rw'),
                    'Dimension' : 'BUFFER',
                    'Width' : buf_range.end_offset - buf_range.start_offset,
                    'FlagUAV' : uav,
                    'data' : [ buf_range.path ]
                }
                resources.append(res)

    for img in unique_texture_resources.values():
        for uav in range(2):
            if uav == 0 and (not img.ro):
                continue
            if uav == 1 and (not img.rw):
                continue
            res = {
                'name' : img.name + ('.ro' if uav == 0 else '.rw'),
                'Dimension' : f'TEXTURE{img.desc.dimension}D',
                'Width' : img.desc.width,
                'Height' : img.desc.height,
                'Format' : to_d3d12_format(img.base_format, True),
                'MipLevels' : img.desc.mips,
                'DepthOrArraySize' : max(img.desc.depth, img.desc.arraysize),
                'PixelSize' : to_d3d12_pixel_size(img.base_format),
                'CastFormats' : [ to_d3d12_format(x, False) for x in img.formats ],
                'data': img.paths
            }

            flags = img.creationFlags
            if flags & rd.TextureCategory.ColorTarget:
                res['FlagRTV'] = 1
            if flags & rd.TextureCategory.DepthTarget:
                res['FlagDSV'] = 1
            if flags & rd.TextureCategory.ShaderReadWrite:
                # This affects performance, so emit it accurately, even for SRVs.
                res['FlagUAV'] = 1

            # For now, only support reading the depth aspect as an SRV for packed depth-stencil.
            match img.base_format.type:
                case rd.ResourceFormatType.D16S8:
                    res['PixelSlice'] = 2
                case rd.ResourceFormatType.D24S8:
                    res['PixelSlice'] = 4
                case rd.ResourceFormatType.D32S8:
                    res['PixelSlice'] = 4
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
            'MaxAnisotropy' : int(samp.maxAnisotropy),
            'MinLOD' : samp.minLOD,
            'MaxLOD' : samp.maxLOD,
            'MipLODBias' : samp.mipBias,
            'Filter' : convert_filter(samp.filter)
        }

        if samp.UseBorder():
            desc['BorderColor'] = [ x for x in samp.borderColorValue.float ]
        desc_samplers.append(desc)

    # Standalone CBVs are always small, so ignore them w.r.t. subrange tracking.
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

        name = f'cbv{blob_index}'
        path = name + '.bin'
        blob_index += 1
        ctx.Replay().BlockInvoke(lambda replayer :
                                 dump_binary_to_file(os.path.join(dir_path, path),
                                                     replayer.GetBufferData(r.descriptor.resource,
                                                                            r.descriptor.byteOffset,
                                                                            r.descriptor.byteSize)))
        res = {
            'name' : name,
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
            if is_uav(r.descriptor.type):
                res = reflection.readWriteResources[r.access.index]
            else:
                res = reflection.readOnlyResources[r.access.index]

            name = res.name

            if res.bindArraySize == 1:
                continue

            desc = { 'HeapOffset' : r.access.arrayElement }
            # Can happen for aliased resources for vectorization purposes, just ignore
            if r.access.arrayElement in used_resource_heap_offsets:
                continue
            used_resource_heap_offsets.add(r.access.arrayElement)

            force_srv = 'SRV' in name
            uav = is_uav(r.descriptor.type) and (not force_srv)

            if is_buffer(r.descriptor.type):
                buf = unique_buffer_resources[r.descriptor.resource]
                buf_range : BufferRange = buf.find_matching_range(r.descriptor.byteOffset, uav)
                if buf_range:
                    desc['Resource'] = buf_range.name + ('.rw' if uav else '.ro')
                    desc['ViewDimension'] = 'BUFFER'

                    if is_typed(r.descriptor.type):
                        if offset_buffer:
                            # Rewrite the offset / size to match the offset buffer values.
                            # Ignore offset buffer for SSBO since no driver should hit that path anymore.
                            offset = r.descriptor.byteOffset + r.descriptor.format.ElementSize() * offset_buffer[4 * r.access.arrayElement + 2]
                            size = r.descriptor.format.ElementSize() * offset_buffer[4 * r.access.arrayElement + 3]
                        else:
                            offset = r.descriptor.byteOffset
                            size = r.descriptor.byteSize

                        desc['Format'] = to_d3d12_format(r.descriptor.format, False)
                        element_size = r.descriptor.format.ElementSize()
                        if (offset - buf_range.start_offset) % element_size != 0:
                            print('TexelBuffer does not align properly to buffer start. Is game using non 64 KiB alignment?')
                        desc['FirstElement'] = (offset - buf_range.start_offset) // element_size
                        desc['NumElements'] = size // element_size
                    else:
                        decoded_name = name.split('_')
                        if len(decoded_name) >= 3:
                            element_size = 0

                            if decoded_name[1] == 'StructuredBuffer':
                                element_size = int(decoded_name[2])
                                desc['StructureByteStride'] = element_size
                            elif decoded_name[1] == 'ByteAddressBuffer':
                                desc['Format'] = 'R32_TYPELESS'
                                desc['Flags'] = 'RAW'
                                element_size = 4
                            else:
                                print(f'Unrecognized resource type {decoded_name[1]}')

                            if (r.descriptor.byteOffset - buf_range.start_offset) % element_size != 0:
                                print('Raw buffer does not align properly to buffer start. Is game using non 64 KiB alignment?')
                            desc['FirstElement'] = (r.descriptor.byteOffset - buf_range.start_offset) // element_size
                            desc['NumElements'] = r.descriptor.byteSize // element_size
                else:
                    print('Could not find matching range?')

            elif is_image(r.descriptor.type):
                img = unique_texture_resources[r.descriptor.resource]
                desc['Resource'] = img.name + ('.rw' if uav else '.ro')
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
                unique_buf = unique_buffer_resources[resid]
                uav = kind == 'UAV'
                buf_range = unique_buf.find_matching_range(offset, uav)
                if buf_range:
                    root_parameters.append({ 'index' : index, 'type' : kind, 'Resource' : buf_range.name + ('.rw' if uav else '.ro'), 'offset' : offset - buf_range.start_offset })
                else:
                    print('Could not find buffer range.')
            else:
                print(f'Failed to lookup BDA {hex(bda)}, cannot dump parameter {index}')
        if kind == 'ResourceTable' or kind == 'SamplerTable':
            root_parameters.append({ 'index' : index, 'type' : kind, 'offset' : push[pushoffset] })
        if kind == 'Constant':
            root_parameters.append({ 'index' : index, 'type' : kind, 'data' : push[pushoffset : pushoffset + pushsize] })

    capture['RootParameters'] = root_parameters

    with open(os.path.join(dir_path, 'capture.json'), 'w') as f:
        print(json.dumps(capture, indent = 4), file = f)

    ctx.SetEventID([], eid, eid)

def register(version : str, ctx : qrd.CaptureContext):
    print(f'Loading exporter for version {version}')
    ctx.Extensions().RegisterWindowMenu(qrd.WindowMenu.Window, ["Export vkd3d-proton to D3D12 Replayer Capture"], export_callback)

def unregister():
    print('Unregistering exporter')

def main():
    with open(sys.argv[1], "rb") as f:
        parse_spirv(f.read())

if __name__ == '__main__':
    main()
