/*--------------------------------------------------------------------
DIVEMesh
Copyright 2008-2026 Hans Bihs

This file is part of DIVEMesh.
--------------------------------------------------------------------*/

#include"topo.h"
#include"dive.h"
#include"lexer.h"

void topo::fluvial_box(lexer *p, dive *a, int rank, int &ts, int &te)
{
    geometry::G300_ds = p->T300_ds;

    p->Darray(geometry::xl,geometry::G300_ds);
    p->Darray(geometry::yl,geometry::G300_ds);
    p->Darray(geometry::xr,geometry::G300_ds);
    p->Darray(geometry::yr,geometry::G300_ds);

    geometry::G300 = p->T300;
    p->Iarray(geometry::G300_ord,geometry::G300);

    for(int n=0;n<geometry::G300;++n)
    geometry::G300_ord[n] = p->T300_ord[n];

    geometry::G301 = p->T301;
    geometry::G305 = p->T305;
    geometry::G306 = p->T306;
    geometry::G307_fh = p->T307_fh;
    geometry::G307_bh = p->T307_bh;
    geometry::G308_x = p->T308_x;
    geometry::G308_y = p->T308_y;
    geometry::G308_z = p->T308_z;
    geometry::G309_x = p->T309_x;
    geometry::G309_y = p->T309_y;
    geometry::G309_z = p->T309_z;

    geometry::G310 = p->T310;
    p->Darray(geometry::G310_l,geometry::G310);
    for(int n=0;n<geometry::G310;++n)
    geometry::G310_l[n] = p->T310_l[n];

    geometry::G320 = p->T320;
    p->Darray(geometry::G320_r,geometry::G320);
    p->Darray(geometry::G320_phi,geometry::G320);
    for(int n=0;n<geometry::G320;++n)
    {
    geometry::G320_r[n] = p->T320_r[n];
    geometry::G320_phi[n] = p->T320_phi[n];
    }

    geometry::G330 = p->T330;
    p->Darray(geometry::G330_r,geometry::G330);
    p->Darray(geometry::G330_phi,geometry::G330);
    for(int n=0;n<geometry::G330;++n)
    {
    geometry::G330_r[n] = p->T330_r[n];
    geometry::G330_phi[n] = p->T330_phi[n];
    }

    geometry::G340 = p->T340;
    p->Darray(geometry::G340_teta,geometry::G340);
    p->Darray(geometry::G340_L,geometry::G340);
    p->Darray(geometry::G340_N,geometry::G340);
    p->Darray(geometry::G340_ds,geometry::G340);
    for(int n=0;n<geometry::G340;++n)
    {
    geometry::G340_teta[n] = p->T340_teta[n];
    geometry::G340_L[n] = p->T340_L[n];
    geometry::G340_N[n] = p->T340_N[n];
    geometry::G340_ds[n] = p->T340_ds[n];
    }

    cout<<"topo fluvial box start"<<endl;

    geometry::countds=1;
    geometry::numds=0;
    geometry::x0=0.0;
    geometry::y0=0.0;
    geometry::phi0=0.0;

    geometry::fluvial_box_fill_segments(p,a,rank,ts,te);
    geometry::fluvial_box_move(p,a);
    geometry::fluvial_box_extend(p,a);

    if(p->T301==1)
    geometry::fluvial_box_v1(p,a,rank,ts,te);

    if(p->T301==2)
    geometry::fluvial_box_v2(p,a,rank,ts,te);

    p->del_Darray(geometry::xl,geometry::G300_ds);
    p->del_Darray(geometry::yl,geometry::G300_ds);
    p->del_Darray(geometry::xr,geometry::G300_ds);
    p->del_Darray(geometry::yr,geometry::G300_ds);

    p->del_Iarray(geometry::G300_ord,geometry::G300);
    p->del_Darray(geometry::G310_l,geometry::G310);
    p->del_Darray(geometry::G320_r,geometry::G320);
    p->del_Darray(geometry::G320_phi,geometry::G320);
    p->del_Darray(geometry::G330_r,geometry::G330);
    p->del_Darray(geometry::G330_phi,geometry::G330);
    p->del_Darray(geometry::G340_teta,geometry::G340);
    p->del_Darray(geometry::G340_L,geometry::G340);
    p->del_Darray(geometry::G340_N,geometry::G340);
    p->del_Darray(geometry::G340_ds,geometry::G340);

    cout<<"topo fluvial box end "<<te<<endl<<endl;
}
