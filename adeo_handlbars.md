<html>
<style>
    @charset "UTF-8";

    body {
        width: 21cm;
        height: 29.7cm;
        margin: 0.5cm 1.5cm;
        font-family: 'Leroy Merlin Sans', 'Helvetica Neue', 'Arial Narrow';
    }

    .header {
        display: flex;
        align-items: center;
        color: #9b9b9b;
        font-family: 'Leroy Merlin Sans', Helvetica, 'Arial';
    }

    .headerinfo {
        padding-left: .5cm;
    }

    .headertitle {
        font-size: 12pt;
        text-transform: uppercase;
        margin: 0;
    }

    .headertext {
        font-size: 7pt;
        margin: 0;
        padding: .1cm 0;
    }

    .order {
        color: #202020;
        margin: 0;
        padding: .1cm 0;
    }

     .logo {
        width: 1.7544520833cm;
        height: 1.0583333333cm;
    }

    main h2 {
        padding: 0;
        margin: .25cm 0 .05cm 0;
        font-family: 'Leroy Merlin Sans', 'Helvetica Neue', 'Arial Narrow';
        color: #202020;
        font-size: 12pt;
        text-transform: uppercase;
        font-weight: normal;
    }

    main fieldset {
        border: none;
        font-size: 10pt;
        font-family: 'Leroy Merlin Sans', 'Helvetica Neue', 'Arial Narrow';
        color: #202020;
        padding: 0;
    }

    .input {
        background: #fff;
        font-size: 9pt;
        font-family: 'Leroy Merlin Sans', 'Helvetica Neue', 'Arial Narrow';
        color: #202020;
        border: 0;
        min-width: 70%;
    }

    .row {
        display: flex;
        justify-content: space-between;
        align-items: start;
    }

    .fieldsetheader {
        margin-top: .2cm;
        display: flex;
        align-items: baseline;
    }

    .fieldsetheader h2 {
        margin: 0;
    }

    .fieldsetheader p {
        font-family: 'Leroy Merlin Sans', 'Helvetica Neue', 'Arial Narrow';
        margin: 0;
        padding-left: .3cm;
    }

    .cell {
        width: 50%;
    }

    textarea {
        border: 0;
        width: 100%;
        height: auto;
        background: #fff;
        font-size: 9pt;
        font-family: 'Leroy Merlin Sans', 'Helvetica Neue', 'Arial Narrow';
        color: #202020;
        overflow-y: hidden;
    }

    textarea.address {
        width: 100%;
        margin-right: 5px;
    }

    .cellborder {
        min-height: 2.5cm;
        border: 1px solid #9b9b9b;
        width: 100%;
        display: flex;
        align-items: flex-end;
        margin-right: .2cm;
    }

    .cellborder:last-child {
        margin: 0;
    }

    .cellborder p {
        padding-left: .3cm
    }

    footer p,
    small,
    .firm {
        font-size: 8pt;
    }

    .textdefault {
        font-family: 'Leroy Merlin Sans', 'Helvetica Neue', 'Arial Narrow';
        font-size: 9pt;
    }

    .list {
        list-style-type: none;
        padding-left: 0;
    }

    .listitem {
        padding-left: 0;
        border-bottom: 1px solid #9b9b9b;
    }

    .subitem {
        padding-left: 10px;
    }

    @media print {
        .block {
            page-break-inside: avoid;
        }

        .no-print,
        .no-print * {
            display: none !important;
        }

    input, select, textarea {
    border: none !important;
}
    }

    .print-page-end {
        page-break-after: right !important;
        clear: both !important;
    }
</style>
<div class="no-print">
    <button type="button" class="btn btn-primary print-button" onclick="window.print()">
    <span class="glyphicon glyphicon-print"></span> PRINT
  </button>
</div>
{{#each tasks}}
<form>
    <header class="header">
        <img itemprop="image" class="logo" src="data:image/webp;base64,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" />
        <section class="headerinfo">
            <h1 class="headertitle">DOCUMENTO DE CONTROL DE TRANSPORTE DE MERCANCÍA POR CARRETERA</h1>
            <div class="row">
                <p class="headertext">
                    Orden FOM/2861/2012 (B.O.E núm. 5 de 05/01/2013).
                </p>
            </div>
            <div class="row">
                <p class="order">Nº Pedido: {{external_id}}</p>
            </div>
        </section>
    </header>
    <main>
        <form>
            <fieldset class="block">
                <section class="fieldsetheader">
                    <h2>Datos de Origen</h2>
                </section>
                <fieldset class="fieldset">
                    <div class="row">
                        <div class="cell"><label for="nombreorigen">Nombre: </label><input id="nombreOrigen" class="input" type="text" value="Leroy Merlin España S.L.U" /></div>
                        <div class="cell"><label for="direccionfiscal">Dirección fiscal: </label><input id="direccionfiscal" class="input" type="text" value="Avda. de la Vega 2, 28108, Alcobendas, Madrid" /></div>
                    </div>
                    <div class="row">
                        <div class="cell"><label for="NIF">NIF: </label><input id="NIF" class="input" type="text" value="B84818442" /></div>
                        <div class="cell"><label for="telefono">Teléfono: </label><input id="telefono" class="input" type="text" value="91 749 60 00" /></div>
                    </div>
                </fieldset>
            </fieldset>
            <fieldset class="block">
                <section class="fieldsetheader">
                    <h2>Datos del cargador</h2>
                </section>
                <fieldset class="fieldset">
                    <div class="row">
                        <div class="cell"><label for="nombretienda">Nombre: </label><input id="nombretienda" class="input" type="text" value="{{way_points.[0].customer.name}}" /></div>
                        <div class="cell"><label for="direcciontienda">Dirección: </label><input id="direcciontienda" class="input" type="text" value="{{way_points.[0].customer.address}}" /></div>
                    </div>
                    <div class="row">
                        <div class="cell"><label for="niftienda">NIF: </label><input id="niftienda" class="input" type="text" value="{{extras.shipper_nif}}" /></div>
                        <div class="cell"><label for="telefono">Teléfono: </label><input id="telefono" class="input" type="text" value="{{way_points.[0].customer.phone}}" /></div>
                    </div>
                </fieldset>
            </fieldset>
            <fieldset class="block">
                <section class="fieldsetheader">
                    <h2>Observaciones al servicio</h2>
                </section>
                <fieldset class="fieldset">{{extras.services.[0].name}} - {{extras.services.[1].name}}</fieldset>
            </fieldset>
            <fieldset class="block">
                <section class="fieldsetheader">
                    <h2>Datos del transportista</h2>
                </section>
                <fieldset class="fieldset">
                    <div class="row">
                        <div class="cell">
                            <label for="nombretransportista">Nombre / Telephono / NIF:</label><br />
                            {{#if (driverBelongsToCompany this)}}{{user.company.name}},{{user.company.phone}},{{user.company.tax_id}}{{/if}}
                        </div>
                        <div class="cell">
                            <label for="direcciontransportista">Dirección: {{#if (driverBelongsToCompany this)}}{{user.company.address}}{{/if}}</label>
                        </div>
                    </div>
                    <div class="row">
                        <div class="cell"><label for="matriculavehiculo">Matrícula vehículo: </label><input id="matriculavehiculo" class="input" type="text" value="{{vehicle.license_plate}}" /></div>
                        {{#if vehicle.trailer}}
                        <div class="cell"><label for="matricularemolque">Matrícula remolque: </label><input id="matricularemolque" class="input" type="text" value="{{vehicle.trailer.license_plate}}" /></div>
                        {{/if}}
                    </div>
                    {{#if extras.special_authorization_id}}
                    <div class="row">
                        <div class="cell"><label for="autorizacionespecial">Nº Autorización especial: </label><input id="autorizacionespecial" class="input" type="text" value="{{extras.special_authorization_id}}" /></div>
                    </div>
                    {{/if}}
                </fieldset>
            </fieldset>
            <fieldset class="block">
                <section class="fieldsetheader">
                    <h2>Fecha de recogida</h2>
                </section>
                <fieldset class="fieldset">
                    <div class="row">
                        <div class="cell"><label for="fecharecogida">Fecha de recogida: </label><input id="fecharecogida" class="input" type="text" value="{{date_only way_points.[0].scheduled_at}}" /></div>
                        <div class="cell"><label for="horarecogida">Hora de recogida: </label><input id="horarecogida" class="input" type="text" value="{{time_only way_points.[0].scheduled_at}}" /></div>
                    </div>
                </fieldset>
            </fieldset>
            <fieldset class="block">
                <section class="fieldsetheader">
                    <h2>Observaciones del transportista</h2>
                </section>
                <fieldset class="fieldset">
                    <div class="row"><textarea maxlength="100">{{getWayPointNote this way_points.[1].id}}</textarea></div>
                </fieldset>
            </fieldset>
            <fieldset class="block">
                <section class="fieldsetheader">
                    <h2>Datos del destino</h2>
                </section>
                <fieldset class="fieldset">
                    <div class="row">
                        <div class="cell"><label for="nombredestino">Nombre cliente: </label><input id="nombredestino" class="input" type="text" value="{{way_points.[1].customer.name}}" /></div>
                        <div class="cell"><label for="direcciondestino">Dirección: </label><input id="direcciondestino" class="input" type="text" value="{{way_points.[1].customer.address}}" /></div>
                    </div>
                    <div class="row">
                        <div class="cell"><label for="localidaddestino">Localidad: </label><input id="localidaddestino" class="input" type="text" value="{{way_points.[1].customer.city}}" /></div>
                        <div class="cell"><label for="codigopostaldestino">Código Postal: </label><input id="codigopostaldestino" class="input" type="text" value="{{way_points.[1].customer.zipcode}}" /></div>
                    </div>
                    <div class="row">
                        <div class="cell"><label for="provinciadestino">Provincia: </label><input id="provinciadestino" class="input" type="text" value="{{way_points.[1].customer.district}}" /></div>
                        <div class="cell"><label for="telefonodestino">Teléfono: </label><input id="telefonodestino" class="input" type="text" value="{{way_points.[1].customer.phone}}" /></div>
                    </div>
                </fieldset>
            </fieldset>
            <fieldset class="block">
                <section class="fieldsetheader">
                    <h2>Datos de la entrega</h2>
                </section>
                <fieldset class="fieldset">
                    <div class="row">
                        <div class="cell"><label for="albaran">Nº de Albarán: </label><input id="albaran" class="input" type="text" value="{{external_id}}" /></div>
                    </div>
                    <div class="row">
                        <div class="cell"><label for="fechaentrega">Fecha de entrega: </label><input id="fechaentrega" class="input" type="text" value="{{date_only way_points.[1].scheduled_at}}" /></div>
                        <div class="cell"><label for="horaentrega">Hora de entrega: </label><input id="horaentrega" class="input" type="text" value="{{time_only way_points.[1].scheduled_at}}" /></div>
                    </div>
                    <div class="row">
                        <div class="cell"><label for="peso">Peso: </label><input id="peso" class="input" type="text" value="{{getTotalWeight this}} KG" /></div>
                        <div class="cell"><label for="bultos">Nº de bultos: </label><input id="bultos" class="input" type="text" value="{{way_points.[1].task_inventories.length}}" /></div>
                    </div>
                </fieldset>
            </fieldset>
            <fieldset class="block">
                <section class="fieldsetheader">
                    <h2>Inventario</h2>
                </section>
                <fieldset class="fieldset">
                    <ul class="list">
                        {{#each way_points.[1].task_inventories}}
                            <li class="listitem">{{#if (has_2wp ..)}}{{scan_string}}{{#if weight}} - {{weight}}kg{{/if}}{{else}}{{original_quantity}} x {{inventory.name}} | {{scan_string}}{{#if weight}} | {{weight}}kg{{/if}}{{/if}}</li>
                            {{#each inventories}}
                                <li class="listitem subitem">{{#if (has_2wp ../..)}}{{original_quantity}} x {{name}}{{#if weight}} - {{weight}}kg{{/if}}{{/if}}</li>
                            {{/each}}
                        {{/each}}
                    </ul>
                </fieldset>
            </fieldset>
            <fieldset>
                <section class="fieldsetheader">
                    <h2>Datos de pago</h2>
                </section>
                <fieldset class="fieldset">
                    <div class="row">
                        <div class="cell"><label for="formapago">Importe: {{delivery_cost}} €</label></div>
                    </div>
                    <div class="row">
                        <div class="cell"><input id="portepagado" checked="checked" type="checkbox" value="pagado" /><label for="portepagado">Portes pagados</label></div>
                        <div class="cell"><input id="portedebido" type="checkbox" value="debido" /><label for="portedebido">Porte debido</label></div>
                    </div>
                </fieldset>
            </fieldset>
            <fieldset class="block">
                <fieldset class="fieldset">
                    <div class="row">
                        <div class="cellborder">
                            <p class="firm">Firma y sello del cargador</p>
                        </div>
                        <div class="cellborder">
                            <p class="firm">Firma y sello del transportista</p>
                        </div>
                        <div class="cellborder">
                            <p class="firm">Firma y sello del destinatario</p>
                        </div>
                    </div>
                </fieldset>
            </fieldset>
            <fieldset class="block">
                <fieldset>
                    <div class="row">
                        <p class="textdefault">Marcar con una X la casilla SI o la casilla NO según el cliente haga entrega o no, respectivamente, de aparato/s usado/s al transportista que presta sus servicios a Bricolaje Bricoman S.L.U. para su correcta gestión según Real Decreto 110/2015, de 20 de febrero, sobre Residuos de Aparatos Eléctricos y Electrónicos (RAEE).</p>
                    </div>
                    <div class="row">
                        <div class="cell"> <label for="si1"> <input id="si1" type="checkbox" value="si1" /> Sí</label> <label for="no1"> <input id="no1" type="checkbox" value="no1" /> NO </label> </div>
                        <div class="cell"> <label for="tipoRAEE1"> Tipo RAEE: </label> <input id="tipoRAEE1" class="input" type="text" value /> </div>
                        <div class="cell"><label for="marcaRAEE1"> Marca: </label> <input id="marcaRAEE1" class="input" type="text" value /> </div>
                    </div>
                    <div class="row">
                        <div class="cell"> <label for="si1"><input id="si2" type="checkbox" value="si1" /> Sí</label> <label for="no1"><input id="no2" type="checkbox" value="no1" /> NO </label> </div>
                        <div class="cell"> <label for="tipoRAEE2"> Tipo RAEE: </label> <input id="tipoRAEE2" class="input" type="text" value /> </div>
                        <div class="cell"> <label for="marcaRAEE2"> Marca: </label> <input id="marcaRAEE2" class="input" type="text" value /> </div>
                    </div>
                    <div class="row">
                        <div class="cell"> <label for="si1"> <input id="si3" type="checkbox" value="si1" /> Sí</label> <label for="no1"> <input id="no3" type="checkbox" value="no1" /> NO </label> </div>
                        <div class="cell"> <label for="tipoRAEE3"> Tipo RAEE: </label> <input id="tipoRAEE3" class="input" type="text" value /> </div>
                        <div class="cell"> <label for="marcaRAEE3"> Marca: </label> <input id="marcaRAEE3" class="input" type="text" value /> </div>
                    </div>
                    <div class="row">
                        <p class="textdefault"> Para el caso de que el cliente haya marcado la opción de NO realizar la entrega del aparato usado y desechado, de características o funcionalidades similares a las del aparato nuevo, se le informa de la posibilidad de entregar el viejo aparato en cualquiera de los puntos de venta de Bricolaje Bricoman S.L.U., en un plazo máximo de 30 días a contar desde la entrega del citado nuevo aparato, siempre y cuando se presente la correspondiente factura de compra del nuevo aparato eléctrico y/o electrónico </p>
                        <div class="cellborder">
                            <p class="firm">Firma del cliente</p>
                        </div>
                    </div>
                </fieldset>
            </fieldset>
        </form>
    </main>
    <footer>
        <p>
            Este documento queda sometido en lo no previsto a las Condiciones
            Generales de Contratación (Orden de 25 de abril de 1997)
        </p>
        <div class="row"> <small>1ª Hoja ejemplar para cliente</small> <small>2ª Hoja ejemplar para transportista</small> <small>3ª Hoja ejemplar para Alcamén</small> </div>
    </footer>
    <div class="print-page-end"> </div>
{{/each}}
</form></html>