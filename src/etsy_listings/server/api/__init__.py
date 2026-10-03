"""The workspace HTTP surface: the app factory and its routers.

The app registers design, template, listing/support, media, listing-template,
batch, SEO, settings and run routers. Nothing is re-exported here:
:func:`etsy_listings.server.api.app.create_app` is the complete application
interface, reached by one path. Re-exporting it would also make importing any
``server.api`` module load the whole app -- including the workers that import
``server.api.schemas`` back -- which is an import cycle waiting for the wrong
import order.

Every path here comes from ``Workspace`` -- and so does every *listing* of
one. That is deliberate rather than stylistic: template names, colours and
design ids arrive from URLs, so routing them through the workspace's accessors
means the "stays inside the root" rule is enforced by the same code the
rest of the tool uses, instead of a second, bespoke check living in the web
layer.

This module used to say that and not mean it. Four private helpers here
globbed ``mockup-templates/{name}/*.png`` and hardcoded ``scene.png``, which
made the calibrator the one place outside ``workspace`` that knew what a
template directory looks like -- and the endpoints are exactly where that is
least affordable. Those questions are now
``Workspace.template_photos``/``template_colours``/``template_preview_photo``.

Request and response shapes live in ``schemas``, except where ``template.yaml``
*is* the payload -- template CRUD reuses ``render.config``'s models directly,
since there is no wire-schema divergence to keep separate.
"""
