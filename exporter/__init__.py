from typing import Optional
import qrenderdoc as qrd
import renderdoc as rd

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

def export_callback(ctx : qrd.CaptureContext, data):
    print('Trying to export ...')
    eid = ctx.CurEvent()
    print('Got EID {}'.format(eid))

    pso : renderdoc.VKState = ctx.CurVulkanPipelineState()
    if pso is None:
        print('Could not find a Vulkan pipeline state.')
        return

    generic_pso : renderdoc.PipeState = ctx.CurPipelineState()

    print('Grabbing push constants')
    push = pso.pushconsts
    print(push)

    ro : List[rd.UsedDescriptor] = generic_pso.GetReadOnlyResources(rd.ShaderStage.Compute)
    rw : List[rd.UsedDescriptor] = generic_pso.GetReadWriteResources(rd.ShaderStage.Compute)

    for r in ro:
        print('RO Desc:')
        print('ArrayElement:', r.access.arrayElement)
        print(r.descriptor)
        print(r.sampler)
    for r in rw:
        print('RW Desc:')
        print('ArrayElement: {}'.format(r.access.arrayElement))
        print('byteOffset: {}'.format(r.descriptor.byteOffset))
        print('byteSize: {}'.format(r.descriptor.byteSize))
        print('format: {}'.format(r.descriptor.format.Name()))
        print('elementSize: {}'.format(r.descriptor.format.ElementSize()))
        print('resource: {}'.format(r.descriptor.resource))
        print('textureType: {}'.format(r.descriptor.textureType))
        print('type: {}'.format(r.descriptor.type))
        print(r.sampler)

        if is_buffer(r.descriptor.type):
            ctx.Replay().BlockInvoke(lambda replayer : print(replayer.GetBufferData(r.descriptor.resource, r.descriptor.byteOffset, r.descriptor.byteSize)))
        elif is_image(r.descriptor.type):
            ctx.Replay().BlockInvoke(lambda replayer : print(replayer.GetBufferData(r.descriptor.resource, r.descriptor.byteOffset, r.descriptor.byteSize)))

    buffers : List[rd.BufferDescription] = ctx.GetBuffers()
    for buf in buffers:
        print('Buffer {} : BDA {}, length {}'.format(buf.resourceId, buf.gpuAddress, buf.length))

def register(version : str, ctx : qrd.CaptureContext):
    print('Loading exporter for version {}'.format(version))
    ctx.Extensions().RegisterWindowMenu(qrd.WindowMenu.Window, ["Export D3D12 Replayer Capture"], export_callback)

def unregister():
    print('Unregistering exporter')
