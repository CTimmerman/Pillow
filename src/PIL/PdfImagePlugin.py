#
# The Python Imaging Library.
# $Id$
#
# PDF (Acrobat) file handling
#
# History:
# 1996-07-16 fl   Created
# 1997-01-18 fl   Fixed header
# 2004-02-21 fl   Fixes for 1/L/CMYK images, etc.
# 2004-02-24 fl   Fixes for 1 and P images.
#
# Copyright (c) 1997-2004 by Secret Labs AB.  All rights reserved.
# Copyright (c) 1996-1997 by Fredrik Lundh.
#
# See the README file for information on usage and redistribution.
#

##
# Image plugin for PDF images (output only).
##

from . import Image, ImageFile, ImageSequence, pdfParser
from ._binary import i8
import io

__version__ = "0.5"


#
# --------------------------------------------------------------------

# object ids:
#  1. catalogue
#  2. pages
#  3. image
#  4. page
#  5. page contents


def _save_all(im, fp, filename):
    _save(im, fp, filename, save_all=True)


##
# (Internal) Image save plugin for the PDF format.

def _save(im, fp, filename, save_all=False):
    resolution = im.encoderinfo.get("resolution", 72.0)
    is_appending = im.encoderinfo.get("append", False)
    if is_appending:
        existing_pdf = pdfParser.PdfParser(f=fp, filename=filename)
        fp.seek(0, io.SEEK_END)
    else:
        existing_pdf = pdfParser.PdfParser()

    #
    # make sure image data is available
    im.load()

    class TextWriter(object):
        def __init__(self, fp):
            self.fp = fp

        def __getattr__(self, name):
            return getattr(self.fp, name)

        def write(self, value):
            self.fp.write(value.encode('latin-1'))

    #fp = TextWriter(fp)

    fp.write(b"%PDF-1.2\n")
    fp.write(b"% created by PIL PDF driver " + __version__.encode("us-ascii") + b"\n")

    #
    # catalogue

    catalog_ref = existing_pdf.next_object_id(fp.tell())
    pages_ref = existing_pdf.next_object_id(0)
    existing_pdf.write_obj(fp, catalog_ref,
        Type=pdfParser.PdfName(b"Catalog"),
        Pages=pages_ref)

    #
    # pages
    ims = [im]
    if save_all:
        append_images = im.encoderinfo.get("append_images", [])
        for append_im in append_images:
            append_im.encoderinfo = im.encoderinfo.copy()
            ims.append(append_im)
    numberOfPages = 0
    image_refs = []
    page_refs = []
    contents_refs = []
    for im in ims:
        im_numberOfPages = 1
        if save_all:
            try:
                im_numberOfPages = im.n_frames
            except AttributeError:
                # Image format does not have n_frames. It is a single frame image
                pass
        numberOfPages += im_numberOfPages
        for i in range(im_numberOfPages):
            image_refs.append(existing_pdf.next_object_id(0))
            page_refs.append(existing_pdf.next_object_id(0))
            contents_refs.append(existing_pdf.next_object_id(0))
            existing_pdf.pages.append(page_refs[-1])

    existing_pdf.write_obj(fp, pages_ref,
        Type=pdfParser.PdfName("Pages"),
        Count=len(existing_pdf.pages),
        Kids=existing_pdf.pages)

    pageNumber = 0
    for imSequence in ims:
        for im in ImageSequence.Iterator(imSequence):
            # FIXME: Should replace ASCIIHexDecode with RunLengthDecode (packbits)
            # or LZWDecode (tiff/lzw compression).  Note that PDF 1.2 also supports
            # Flatedecode (zip compression).

            bits = 8
            params = None

            if im.mode == "1":
                filter = "ASCIIHexDecode"
                colorspace = pdfParser.PdfName("DeviceGray")
                procset = "ImageB"  # grayscale
                bits = 1
            elif im.mode == "L":
                filter = "DCTDecode"
                # params = "<< /Predictor 15 /Columns %d >>" % (width-2)
                colorspace = pdfParser.PdfName("DeviceGray")
                procset = "ImageB"  # grayscale
            elif im.mode == "P":
                filter = "ASCIIHexDecode"
                palette = im.im.getpalette("RGB")
                colorspace = [pdfParser.PdfName("Indexed"), pdfParser.PdfName("DeviceRGB"), 255, pdfParser.PdfBinary(palette)]
                procset = "ImageI"  # indexed color
            elif im.mode == "RGB":
                filter = "DCTDecode"
                colorspace = pdfParser.PdfName("DeviceRGB")
                procset = "ImageC"  # color images
            elif im.mode == "CMYK":
                filter = "DCTDecode"
                colorspace = pdfParser.PdfName("DeviceCMYK")
                procset = "ImageC"  # color images
            else:
                raise ValueError("cannot save mode %s" % im.mode)

            #
            # image

            op = io.BytesIO()

            if filter == "ASCIIHexDecode":
                if bits == 1:
                    # FIXME: the hex encoder doesn't support packed 1-bit
                    # images; do things the hard way...
                    data = im.tobytes("raw", "1")
                    im = Image.new("L", (len(data), 1), None)
                    im.putdata(data)
                ImageFile._save(im, op, [("hex", (0, 0)+im.size, 0, im.mode)])
            elif filter == "DCTDecode":
                Image.SAVE["JPEG"](im, op, filename)
            elif filter == "FlateDecode":
                ImageFile._save(im, op, [("zip", (0, 0)+im.size, 0, im.mode)])
            elif filter == "RunLengthDecode":
                ImageFile._save(im, op, [("packbits", (0, 0)+im.size, 0, im.mode)])
            else:
                raise ValueError("unsupported PDF filter (%s)" % filter)

            #
            # Get image characteristics

            width, height = im.size

            existing_pdf.write_obj(fp, image_refs[pageNumber], stream=op.getvalue(),
                Type=pdfParser.PdfName("XObject"),
                Subtype=pdfParser.PdfName("Image"),
                Width=width,  # * 72.0 / resolution,
                Height=height,  # * 72.0 / resolution,
                Filter=pdfParser.PdfName(filter),
                BitsPerComponent=bits,
                DecodeParams=params,
                ColorSpace=colorspace)

            #
            # page

            existing_pdf.write_obj(fp, page_refs[pageNumber],
                Type=pdfParser.PdfName("Page"),
                Parent=pages_ref,
                Resources=pdfParser.PdfDict(
                    ProcSet=[pdfParser.PdfName("PDF"), pdfParser.PdfName(procset)],
                    XObject=pdfParser.PdfDict(image=image_refs[pageNumber])),
                MediaBox=[0, 0, int(width * 72.0 / resolution), int(height * 72.0 / resolution)],
                Contents=contents_refs[pageNumber]
                )

            #
            # page contents

            op = TextWriter(io.BytesIO())

            op.write(
                "q %d 0 0 %d 0 0 cm /image Do Q\n" % (
                    int(width * 72.0 / resolution),
                    int(height * 72.0 / resolution)))

            existing_pdf.write_obj(fp, contents_refs[pageNumber], stream=op.fp.getvalue())

            pageNumber += 1

    #
    # trailer
    existing_pdf.write_xref_and_trailer(fp, catalog_ref)
    if hasattr(fp, "flush"):
        fp.flush()

#
# --------------------------------------------------------------------

Image.register_save("PDF", _save)
Image.register_save_all("PDF", _save_all)

Image.register_extension("PDF", ".pdf")

Image.register_mime("PDF", "application/pdf")
