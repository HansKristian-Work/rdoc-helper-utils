# rdoc-utils

My dumping ground for RenderDoc UI extensions.

Copy to ~/.local/share/qrenderdoc/extensions/.

### Note to self: Internal self capture hackery

```
# Build selfhost
cmake .. -DCMAKE_BUILD_TYPE=Release -DINTERNAL_SELF_CAPTURE=ON -DENABLE_GL=OFF -DENABLE_GLES=OFF

# Capture from selfhost
RDOC_CAPTURE_EID=$EID ./build-selfhost/bin/rdocselfcmd capture qrenderdoc /tmp/test.rdc
```

`VKD3D_CONFIG=nodxr` to avoid BDA cycle issues.
Patch qrenderdoc using `0001-Hacks-for-self-capture.patch`.

