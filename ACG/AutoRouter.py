from .AyarLayoutGenerator import AyarLayoutGenerator
from .Rectangle import Rectangle
from .XY import XY
from .tech import tech_info
from typing import Tuple, Union, Optional, List


class AutoRouter:
    """
    The Autorouter class provides a number of methods to automatically generate simple wire routes in ACG
    """

    def __init__(self,
                 gen_cls: AyarLayoutGenerator,
                 start_rect: Rectangle,
                 start_direction: str,
                 config: Optional[dict] = None
                 ):
        """
        Expects an ACG layout generator as input. This generator class has its shape creation methods called after the
        route is completed

        Parameters
        ----------
        gen_cls : AyarLayoutGenerator
            Layout generator class that this Autorouter will be drawing in
        start_rect : Rectangle
            The rectangle we will be starting the route from
        start_direction : str
            '+x', '-x', '+y', '-y' for the direction the route will start from
        config : dict
            dictionary of configuration variables that will set router defaults
        """
        # Init generator and tech information
        self.gen: AyarLayoutGenerator = gen_cls
        self.tech = self.gen.tech
        self.acg_tech = tech_info['metal_tech']
        self.config = config

        # State variables for where the route will be going
        self.current_rect = self.gen.copy_rect(start_rect)
        self.current_dir = start_direction
        self.current_handle: str = ''
        self.layer = start_rect.layer

        # Set the current rectangle handle based on the starting direction
        self._set_handle_from_dir(direction=start_direction)

        # Location dictionary to store the running components in the route
        self.loc = dict(
            route_list=[self.current_rect],
            rect_list=[self.current_rect],
            via_list=[],
        )

    def draw_straight_route(self,
                            loc: Union[Tuple[float, float], XY],
                            width: Optional[float] = None
                            ) -> 'AutoRouter':
        """
        Routes a straight metal line from the current location of specified length. This
        method does not change the current routing direction.

        Note: This method relies on the fact that stretching a rectangle with an offset
        but without a reference rectangle uses the offset as an absolute reference loc

        Parameters
        ----------
        loc : Optional[Tuple[float, float]]
            XY location to route to. This method will only route in the current direction
        width : Optional[float]
            TODO: Draws the new route segment with this width if provided

        Returns
        -------
        self : AutoRouter
            Return self to make it easy to cascade connections
        """
        if self.current_dir == '+x' or self.current_dir == '-x':
            stretch_opt = (True, False)
        else:
            stretch_opt = (False, True)
        self.current_rect.stretch(target_handle=self.current_handle,
                                  offset=loc,
                                  stretch_opt=stretch_opt)
        return self

    def draw_via(self,
                 layer: Union[str, Tuple[str, str]],
                 direction: str,
                 out_width: float,
                 size: Optional[Tuple[int, int]] = None,
                 enc_bot: Optional[List[float]] = None,
                 enc_top: Optional[List[float]] = None,
                 ) -> 'AutoRouter':
        """
        This method adds a via at the current location to the user provided layer. Cannot
        move by more than one layer at a time

        This method will change the current rectangle and can change the current routing
        direction

        Parameters
        ----------
        layer : Union[str, Tuple[str, str]]
            layer or lpp of the metal to via up/down to
        direction : str
            '+x', '-x', '+y', '-y' for the direction the new route segment will start from
        out_width : Optional[float]
            width of the output wire to be drawn on the new metal layer
        size : Optional[Tuple[int, int]]
            number of vias to place in the array
        enc_bot : List[float]
            enclosure size of the left, bottom, right, top edges of the bottom layer of the via
        enc_top : List[float]
            enclosure size of the left, bottom, right, top edges of the top layer of the via

        Returns
        -------
        self : AutoRouter
            Return self to make it easy to cascade connections
        """
        # Create the new rectangle and align it to the end of the route
        new_rect = self.gen.add_rect(layer=layer)
        new_rect.align(target_handle='c',
                       ref_rect=self.current_rect,
                       ref_handle=self.current_handle)

        # Match the route width of the current route
        if self.current_dir == '+x' or self.current_dir == '-x':
            new_rect.set_dim('y', size=self.current_rect.get_dim('y'))
        else:
            new_rect.set_dim('x', size=self.current_rect.get_dim('x'))

        # Size the new rectangle to match the output width
        if direction == '+x' or direction == '-x':
            new_rect.set_dim('y', out_width)
        else:
            new_rect.set_dim('x', out_width)

        # If the provided layer is the same as the current layer, turn the route
        # instead of adding a new via
        if layer != self.current_rect.layer:
            # Add a new primitive via at the current location
            via_id = 'V' + self.current_rect.layer + '_' + layer
            via = self.gen.add_prim_via(via_id=via_id, rect=new_rect)

            # Set via parameters
            if size is not None:
                via.size = size
            else:
                via.size = (1, 1)
            if enc_bot is not None:
                via.set_enclosure(enc_bot=enc_bot)
            if enc_top is not None:
                via.set_enclosure(enc_top=enc_top)

        # Update the pointers for the current rect, handle, and direction
        self.current_rect = new_rect
        self.current_dir = direction
        self._set_handle_from_dir(direction)

        return self

    def draw_l_route(self,
                     loc: Union[Tuple[float, float], XY],
                     out_width: Optional[float] = None,
                     layer: Optional[Union[str, Tuple[str, str]]] = None,
                     ) -> 'AutoRouter':
        """
        Draws an L-route from the current location to the provided location while minimizing
        the number of turns.

        Parameters
        ----------
        loc : Union[Tuple[float, float], XY]
            Final location of the route
        out_width : Optional[float]
            If provided, will set the second segment of the l-route to match this width, otherwise
            will maintain the same width
        layer : Optional[Union[str, Tuple[str, str]]]
            If provided will draw the second segment of the l-route on this metal layer, otherwise
            will stay on the same layer

        Returns
        -------
        self : AutoRouter
            Return self to make it easy to cascade connections
        """
        # Draw the first straight route segment
        self.draw_straight_route(loc=loc)

        # Draw the via to turn the l-route
        # If layer is None, stay on the same layer
        if not layer:
            layer = self.current_rect.layer
        # If an output width is not provided, use the same as the current width
        if not out_width:
            if self.current_dir == '+x' or self.current_dir == '-x':
                out_width = self.current_rect.get_dim('y')
            else:
                out_width = self.current_rect.get_dim('x')
        # Determine the output direction
        if self.current_dir == '+x' or self.current_dir == '-x':
            if self.current_rect[self.current_handle].y < XY(loc).y:
                direction = '+y'
            else:
                direction = '-y'
        else:
            if self.current_rect[self.current_handle].x < XY(loc).x:
                direction = '+x'
            else:
                direction = '-x'
        self.draw_via(layer=layer,
                      direction=direction,
                      out_width=out_width)

        # Draw the final straight route segment
        self.draw_straight_route(loc=loc)

        return self

    ''' Old Routing Methods to be Deprecated '''

    def stretch_l_route(self,
                        start_rect: Rectangle,
                        start_dir: str,
                        end_rect: Rectangle,
                        via_size: Tuple[int, int] = (None, None)
                        ):
        """
        This method takes a starting rectangle and an ending rectangle and automatically routes an L between them

        Parameters
        ----------
        start_rect : Rectangle
            The location where the route will be started
        start_dir : str
            'x' or 'y' for the direction the first segment in the l route will traverse
        end_rect : Rectangle
            The location where the route will be ended
        via_size : Tuple[int, int]
            Overrides the array size of the via to be placed.

        Returns
        -------
        route : Route
            The created route object containing all of the rects and vias
        """
        if via_size != (None, None):
            print('WARNING, explicit via size is not yet supported')

        rect1 = self.gen.copy_rect(start_rect)
        rect2 = self.gen.copy_rect(end_rect)
        if start_dir == 'y':
            if rect2['t'] > rect1['t']:
                rect1.stretch('t', ref_rect=rect2, ref_handle='t')
                if rect2['c'].x > rect1['c'].x:
                    rect2.stretch('l', ref_rect=rect1, ref_handle='l')
                else:
                    rect2.stretch('r', ref_rect=rect1, ref_handle='r')
            else:
                rect1.stretch('b', ref_rect=rect2, ref_handle='b')
                if rect2['c'].x > rect1['c'].x:
                    rect2.stretch('l', ref_rect=rect1, ref_handle='l')
                else:
                    rect2.stretch('r', ref_rect=rect1, ref_handle='r')
        else:
            if rect2['r'] > rect1['r']:
                rect1.stretch('r', ref_rect=rect2, ref_handle='r')
                if rect2['c'].y > rect1['c'].y:
                    rect2.stretch('b', ref_rect=rect1, ref_handle='b')
                else:
                    rect2.stretch('t', ref_rect=rect1, ref_handle='t')
            else:
                rect1.stretch('l', ref_rect=rect2, ref_handle='l')
                if rect2['c'].y > rect1['c'].y:
                    rect2.stretch('b', ref_rect=rect1, ref_handle='b')
                else:
                    rect2.stretch('t', ref_rect=rect1, ref_handle='t')
        self.gen.connect_wires(rect1=rect1, rect2=rect2, size=via_size)

    def _set_handle_from_dir(self, direction: str) -> None:
        """ Determines the current rectangle handle based on the provided routing direction """
        if direction == '+x':
            self.current_handle = 'cr'
        elif direction == '-x':
            self.current_handle = 'cl'
        elif direction == '+y':
            self.current_handle = 'ct'
        elif direction == '-y':
            self.current_handle = 'cb'


class Route:
    """
    This class contains a list of rectangles and vias which describe a continuous route from one location to another.
    Also contains convenience methods to modify the shape of the route
    """

    def __init__(self,
                 gen_cls: AyarLayoutGenerator,
                 start_loc: XY,
                 start_dir: str,
                 start_rect: Rectangle = None,
                 ):
        self.gen = gen_cls  # Class where we will be drawing the route
        self.route_list = []  # Contains the full list of rects and vias

        # Pointers to route in progress
        self.current_rect = start_rect  # Contains the current rectangle being routed
        self.current_dir = start_dir  # direction that the current rectangle is routing in
        self.current_loc = start_loc  # pointer to the center location of the current route

    def add_via(self, target_layer: str):
        """
        Places a via at the current location from the current rect's layer to the target_layer

        Parameters
        ----------
        target_layer: str
            the ending metal layer of the via stack
        """
        pass

    def straight_route(self,
                       location: XY,
                       width: float = None,
                       direction: str = None
                       ) -> None:
        """
        Stretches the current route to move the provided location in a single direction

        Parameters
        ----------
        location : XY
            Location that the new route will be routed to
        width : float
            Width of the metal in microns. If None, defaults to the current rectangles width
        direction : str
            'x' or 'y' for which direction the current rectangle will be stretched. If None, defaults to the current
            direction
        """
        if direction is None:
            direction = self.current_dir
        if width is None:
            if direction == 'x':
                width = self.current_rect.get_dim('y')
            if direction == 'y':
                width = self.current_rect.get_dim('x')

        seg, end = self.draw_path_segment(start=self.current_loc,
                                          layer=self.current_rect.layer,
                                          width=width,
                                          direction=direction,
                                          end=location)
        print(seg, end)
        self.update_route_pointer(seg, end)

    def update_route_pointer(self, rect: Rectangle, loc: XY) -> None:
        self.route_list.append(rect)
        self.current_rect = rect
        self.current_loc = loc

    def draw_path_segment(self,
                          start: XY,
                          layer: str,
                          width: float,
                          direction: str,
                          end: XY
                          ) -> Tuple[Rectangle, XY]:
        """
        This method manually draws the specified rectangle. This method does not place vias. If the end and start coords
        do not share an x or y coordinate, the path is only drawn in the provided direction.

        Parameters
        ----------
        start : XY
            starting location of the path segment
        layer : str
            layer for the rectangle to be drawn
        width : float
            width of the route perpendicular to its direction
        direction : str
            direction in which the route will be drawn
        end : XY
            ending location of the path segment
        """
        seg = self.gen.add_rect(layer=layer)  # Create a new rectangle

        # Set the size of the rectangle and align it to the starting point
        if direction == 'x':
            seg.set_dim(dim='x', size=abs(end.x - start.x))
            seg.set_dim(dim='y', size=width)
            if end.x > start.x:
                seg.align(target_handle='cl', offset=start)
                end_loc = seg['cr']
            else:
                seg.align(target_handle='cr', offset=start)
                end_loc = seg['cl']
        else:
            seg.set_dim(dim='x', size=width)
            seg.set_dim(dim='y', size=abs(end.y - start.y))
            if end.y > start.y:
                seg.align(target_handle='cb', offset=start)
                end_loc = seg['ct']
            else:
                seg.align(target_handle='ct', offset=start)
                end_loc = seg['cb']
        return seg, end_loc
