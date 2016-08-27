import os
import re
from parser.tl_parser import TLParser
from parser.source_builder import SourceBuilder


def generate_tlobjecs():
    """Generates all the TLObjects from scheme.tl to tl/functions and tl/types"""

    # First ensure that the required parent directories exist
    os.makedirs('tl/functions', exist_ok=True)
    os.makedirs('tl/types', exist_ok=True)

    tlobjects = tuple(TLParser.parse_file('scheme.tl'))
    for tlobject in tlobjects:
        # Determine the output directory and create it
        out_dir = os.path.join('tl',
                               'functions' if tlobject.is_function
                               else 'types')

        if tlobject.namespace is not None:
            out_dir = os.path.join(out_dir, tlobject.namespace)

        os.makedirs(out_dir, exist_ok=True)

        init_py = os.path.join(out_dir, '__init__.py')
        # Also create __init__.py
        if not os.path.isfile(init_py):
            open(init_py, 'a').close()

        # Create the file
        filename = os.path.join(out_dir, get_file_name(tlobject, add_extension=True))
        with open(filename, 'w', encoding='utf-8') as file:
            # Let's build the source code!
            with SourceBuilder(file) as builder:
                builder.writeln('from requests.mtproto_request import MTProtoRequest')
                builder.writeln()
                builder.writeln()
                builder.writeln('class {}(MTProtoRequest):'.format(get_class_name(tlobject)))

                # Write the original .tl definition, along with a "generated automatically" message
                builder.writeln('"""Class generated by TLObjects\' generator. '
                                'All changes will be ERASED. Original .tl definition below.')
                builder.writeln('{}"""'.format(tlobject))
                builder.writeln()

                # First sort the arguments so that those not being a flag come first
                args = sorted([arg for arg in tlobject.args if not arg.flag_indicator],
                              key=lambda x: x.is_flag)

                # Then convert the args to string parameters, the flags having =None
                args = [(arg.name if not arg.is_flag
                        else '{}=None'.format(arg.name)) for arg in args
                        if not arg.flag_indicator and not arg.generic_definition]

                # Write the __init__ function
                if args:
                    builder.writeln('def __init__(self, {}):'.format(', '.join(args)))
                else:
                    builder.writeln('def __init__(self):')

                # Now update args to have the TLObject arguments, _except_
                # those which are generated automatically: flag indicator and generic definitions.
                # We don't need the generic definitions in Python because arguments can be any type
                args = [arg for arg in tlobject.args
                        if not arg.flag_indicator and not arg.generic_definition]

                if args:
                    # Write the docstring, so we know the type of the arguments
                    builder.writeln('"""')
                    for arg in args:
                        if not arg.flag_indicator:
                            builder.write(':param {}: Telegram type: «{}».'.format(arg.name, arg.type))
                            if arg.is_vector:
                                builder.write(' Must be a list.'.format(arg.name))
                            if arg.is_generic:
                                builder.write(' This should be another MTProtoRequest.')
                            builder.writeln()
                    builder.writeln('"""')

                builder.writeln('super().__init__()')
                # Functions have a result object
                if tlobject.is_function:
                    builder.writeln('self.result = None')

                # Leave an empty line if there are any args
                if args:
                    builder.writeln()

                for arg in args:
                    builder.writeln('self.{0} = {0}'.format(arg.name))
                builder.end_block()

                # Write the on_send(self, writer) function
                builder.writeln('def on_send(self, writer):')
                builder.writeln("writer.write_int({})  # {}'s constructor ID"
                                .format(hex(tlobject.id), tlobject.name))

                for arg in tlobject.args:
                    write_onsend_code(builder, arg, tlobject.args)
                builder.end_block()

                # Write the on_response(self, reader) function
                builder.writeln('def on_response(self, reader):')
                # Do not read constructor's ID, since that's already been read somewhere else
                if tlobject.is_function:
                    builder.writeln('self.result = reader.tgread_object()')
                else:
                    if tlobject.args:
                        for arg in tlobject.args:
                            write_onresponse_code(builder, arg, tlobject.args)
                    else:
                        builder.writeln('pass')
                builder.end_block()

    # Once all the objects have been generated, we can now group them in a single file
    filename = os.path.join('tl', 'all_tlobjects.py')
    with open(filename, 'w', encoding='utf-8') as file:
        with SourceBuilder(file) as builder:
            builder.writeln('"""File generated by TLObjects\' generator. All changes will be ERASED"""')
            builder.writeln()

            # First add imports
            for tlobject in tlobjects:
                builder.writeln('import {}'.format(get_full_file_name(tlobject)))
            builder.writeln()

            # Then create the dictionary containing constructor_id: class
            builder.writeln('tlobjects = {')
            builder.current_indent += 1

            for tlobject in tlobjects:
                builder.writeln('{}: {}.{},'.format(
                    hex(tlobject.id),
                    get_full_file_name(tlobject),
                    get_class_name(tlobject)
                ))

            builder.current_indent -= 1
            builder.writeln('}')


def get_class_name(tlobject):
    # Courtesy of http://stackoverflow.com/a/31531797/4759433
    # Also, '_' could be replaced for ' ', then use .title(), and then remove ' '
    result = re.sub(r'_([a-z])', lambda m: m.group(1).upper(), tlobject.name)
    return result[:1].upper() + result[1:].replace('_', '')  # Replace again to fully ensure!


def get_full_file_name(tlobject):
    fullname = get_file_name(tlobject, add_extension=False)
    if tlobject.namespace is not None:
        fullname = '{}.{}'.format(tlobject.namespace, fullname)

    if tlobject.is_function:
        return 'tl.functions.{}'.format(fullname)
    else:
        return 'tl.types.{}'.format(fullname)


def get_file_name(tlobject, add_extension):
    # Courtesy of http://stackoverflow.com/a/1176023/4759433
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', tlobject.name)
    result = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
    if add_extension:
        return result + '.py'
    else:
        return result


def write_onsend_code(builder, arg, args, name=None):
    """
    Writes the write code for the given argument
    :param builder: The source code builder
    :param arg: The argument to write
    :param args: All the other arguments in TLObject same on_send. This is required to determine the flags value
    :param name: The name of the argument. Defaults to «self.argname»
                 This argument is an option because it's required when writing Vectors<>
    """

    if arg.generic_definition:
        return  # Do nothing, this only specifies a later type

    if name is None:
        name = 'self.{}'.format(arg.name)

    # The argument may be a flag, only write if it's not None!
    if arg.is_flag:
        builder.writeln('if {} is not None:'.format(name))

    if arg.is_vector:
        builder.writeln("writer.write_int(0x1cb5c415)  # Vector's constructor ID")
        builder.writeln('writer.write_int(len({}))'.format(name))
        builder.writeln('for {}_item in {}:'.format(arg.name, name))
        # Temporary disable .is_vector, not to enter this if again
        arg.is_vector = False
        write_onsend_code(builder, arg, args, name='{}_item'.format(arg.name))
        arg.is_vector = True

    elif arg.flag_indicator:
        # Calculate the flags with those items which are not None
        builder.writeln('# Calculate the flags. This equals to those flag arguments which are NOT None')
        builder.writeln('flags = 0')
        for flag in args:
            if flag.is_flag:
                builder.writeln('flags |= (1 << {}) if {} is not None else 0'
                                .format(flag.flag_index, 'self.{}'.format(flag.name)))

        builder.writeln('writer.write_int(flags)')
        builder.writeln()

    elif 'int' == arg.type:
        builder.writeln('writer.write_int({})'.format(name))

    elif 'long' == arg.type:
        builder.writeln('writer.write_long({})'.format(name))

    elif 'int128' == arg.type:
        builder.writeln('writer.write_large_int({}, bits=128)'.format(name))

    elif 'int256' == arg.type:
        builder.writeln('writer.write_large_int({}, bits=256)'.format(name))

    elif 'double' == arg.type:
        builder.writeln('writer.write_double({})'.format(name))

    elif 'string' == arg.type:
        builder.writeln('writer.tgwrite_string({})'.format(name))

    elif 'Bool' == arg.type:
        builder.writeln('writer.tgwrite_bool({})'.format(name))

    elif 'true' == arg.type:  # Awkwardly enough, Telegram has both bool and "true", used in flags
        builder.writeln('writer.write_int(0x3fedd339)  # true')

    elif 'bytes' == arg.type:
        builder.writeln('writer.write({})'.format(name))

    else:
        # Else it may be a custom type
        builder.writeln('{}.write(writer)'.format(name))

    # End vector and flag blocks if required (if we opened them before)
    if arg.is_vector:
        builder.end_block()

    if arg.is_flag:
        builder.end_block()


def write_onresponse_code(builder, arg, args, name=None):
    """
    Writes the receive code for the given argument

    :param builder: The source code builder
    :param arg: The argument to write
    :param args: All the other arguments in TLObject same on_send. This is required to determine the flags value
    :param name: The name of the argument. Defaults to «self.argname»
                 This argument is an option because it's required when writing Vectors<>
    """

    if arg.generic_definition:
        return  # Do nothing, this only specifies a later type

    if name is None:
        name = 'self.{}'.format(arg.name)

    # The argument may be a flag, only write that flag was given!
    if arg.is_flag:
        builder.writeln('if (flags & (1 << {})) != 0:'.format(arg.flag_index))

    if arg.is_vector:
        builder.writeln("reader.read_int()  # Vector's constructor ID")
        builder.writeln('{} = []  # Initialize an empty list'.format(name))
        builder.writeln('{}_len = reader.read_int()'.format(name))
        builder.writeln('for _ in range({}_len):'.format(name))
        # Temporary disable .is_vector, not to enter this if again
        arg.is_vector = False
        write_onresponse_code(builder, arg, args, name='{}_item'.format(arg.name))
        builder.writeln('{}.append({}_item)'.format(name, arg.name))
        arg.is_vector = True

    elif arg.flag_indicator:
        # Read the flags, which will indicate what items we should read next
        builder.writeln('flags = reader.read_int()')
        builder.writeln()

    elif 'int' == arg.type:
        builder.writeln('{} = reader.read_int()'.format(name))

    elif 'long' == arg.type:
        builder.writeln('{} = reader.read_long()'.format(name))

    elif 'int128' == arg.type:
        builder.writeln('{} = reader.read_large_int(bits=128)'.format(name))

    elif 'int256' == arg.type:
        builder.writeln('{} = reader.read_large_int(bits=256)'.format(name))

    elif 'double' == arg.type:
        builder.writeln('{} = reader.read_double()'.format(name))

    elif 'string' == arg.type:
        builder.writeln('{} = reader.tgread_string()'.format(name))

    elif 'Bool' == arg.type:
        builder.writeln('{} = reader.tgread_bool()'.format(name))

    elif 'true' == arg.type:  # Awkwardly enough, Telegram has both bool and "true", used in flags
        builder.writeln('{} = reader.read_int() == 0x3fedd339  # true'.format(name))

    elif 'bytes' == arg.type:
        builder.writeln('{} = reader.read()'.format(name))

    else:
        # Else it may be a custom type
        builder.writeln('{} = reader.tgread_object(reader)'.format(name))

    # End vector and flag blocks if required (if we opened them before)
    if arg.is_vector:
        builder.end_block()

    if arg.is_flag:
        builder.end_block()


def get_code(tg_type, stream_name, arg_name):
    function_name = 'write' if stream_name == 'writer' else 'read'
